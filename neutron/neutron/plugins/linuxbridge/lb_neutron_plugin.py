# Copyright (c) 2012 OpenStack Foundation.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import sys

from oslo.config import cfg

from neutron.agent import securitygroups_rpc as sg_rpc
from neutron.api.rpc.agentnotifiers import dhcp_rpc_agent_api
from neutron.api.rpc.agentnotifiers import l3_rpc_agent_api
from neutron.api.v2 import attributes
from neutron.common import constants as q_const
from neutron.common import exceptions as n_exc
from neutron.common import rpc as q_rpc
from neutron.common import topics
from neutron.common import utils
from neutron.db import agents_db
from neutron.db import agentschedulers_db
from neutron.db import api as db_api
from neutron.db import db_base_plugin_v2
from neutron.db import dhcp_rpc_base
from neutron.db import external_net_db
from neutron.db import extraroute_db
from neutron.db import l3_agentschedulers_db
from neutron.db import l3_gwmode_db
from neutron.db import l3_rpc_base
from neutron.db import portbindings_db
from neutron.db import quota_db  # noqa
from neutron.db import securitygroups_rpc_base as sg_db_rpc
from neutron.extensions import portbindings
from neutron.extensions import providernet as provider
from neutron import manager
from neutron.openstack.common import importutils
from neutron.openstack.common import log as logging
from neutron.openstack.common import rpc
from neutron.openstack.common.rpc import proxy
from neutron.plugins.common import constants as svc_constants
from neutron.plugins.common import utils as plugin_utils
from neutron.plugins.linuxbridge.common import constants
from neutron.plugins.linuxbridge.db import l2network_db_v2 as db


LOG = logging.getLogger(__name__)


class LinuxBridgeRpcCallbacks(dhcp_rpc_base.DhcpRpcCallbackMixin,
                              l3_rpc_base.L3RpcCallbackMixin,
                              sg_db_rpc.SecurityGroupServerRpcCallbackMixin
                              ):

    # history
    #   1.1 Support Security Group RPC
    RPC_API_VERSION = '1.1'
    # Device names start with "tap"
    TAP_PREFIX_LEN = 3

    def create_rpc_dispatcher(self):
        '''Get the rpc dispatcher for this manager.

        If a manager would like to set an rpc API version, or support more than
        one class as the target of rpc messages, override this method.
        '''
        return q_rpc.PluginRpcDispatcher([self,
                                          agents_db.AgentExtRpcCallback()])

    @classmethod
    def get_port_from_device(cls, device):
        port = db.get_port_from_device(device[cls.TAP_PREFIX_LEN:])
        if port:
            port['device'] = device
        return port

    def get_device_details(self, rpc_context, **kwargs):
        """Agent requests device details."""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        LOG.debug(_("Device %(device)s details requested from %(agent_id)s"),
                  {'device': device, 'agent_id': agent_id})
        port = self.get_port_from_device(device)
        if port:
            binding = db.get_network_binding(db_api.get_session(),
                                             port['network_id'])
            (network_type,
             segmentation_id) = constants.interpret_vlan_id(binding.vlan_id)
            entry = {'device': device,
                     'network_type': network_type,
                     'physical_network': binding.physical_network,
                     'segmentation_id': segmentation_id,
                     'network_id': port['network_id'],
                     'port_id': port['id'],
                     'admin_state_up': port['admin_state_up']}
            if cfg.CONF.AGENT.rpc_support_old_agents:
                entry['vlan_id'] = binding.vlan_id
            new_status = (q_const.PORT_STATUS_ACTIVE if port['admin_state_up']
                          else q_const.PORT_STATUS_DOWN)
            if port['status'] != new_status:
                db.set_port_status(port['id'], new_status)
        else:
            entry = {'device': device}
            LOG.debug(_("%s can not be found in database"), device)
        return entry

    def update_device_down(self, rpc_context, **kwargs):
        """Device no longer exists on agent."""
        # TODO(garyk) - live migration and port status
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        host = kwargs.get('host')
        port = self.get_port_from_device(device)
        LOG.debug(_("Device %(device)s no longer exists on %(agent_id)s"),
                  {'device': device, 'agent_id': agent_id})
        plugin = manager.NeutronManager.get_plugin()
        if port:
            entry = {'device': device,
                     'exists': True}
            if (host and not
                plugin.get_port_host(rpc_context, port['id']) == host):
                LOG.debug(_("Device %(device)s not bound to the"
                            " agent host %(host)s"),
                          {'device': device, 'host': host})
            elif port['status'] != q_const.PORT_STATUS_DOWN:
                # Set port status to DOWN
                db.set_port_status(port['id'], q_const.PORT_STATUS_DOWN)
        else:
            entry = {'device': device,
                     'exists': False}
            LOG.debug(_("%s can not be found in database"), device)
        return entry

    def update_device_up(self, rpc_context, **kwargs):
        """Device is up on agent."""
        agent_id = kwargs.get('agent_id')
        device = kwargs.get('device')
        host = kwargs.get('host')
        port = self.get_port_from_device(device)
        LOG.debug(_("Device %(device)s up on %(agent_id)s"),
                  {'device': device, 'agent_id': agent_id})
        plugin = manager.NeutronManager.get_plugin()
        if port:
            if (host and
                not plugin.get_port_host(rpc_context, port['id']) == host):
                LOG.debug(_("Device %(device)s not bound to the"
                            " agent host %(host)s"),
                          {'device': device, 'host': host})
                return
            elif port['status'] != q_const.PORT_STATUS_ACTIVE:
                db.set_port_status(port['id'],
                                   q_const.PORT_STATUS_ACTIVE)
        else:
            LOG.debug(_("%s can not be found in database"), device)


class AgentNotifierApi(proxy.RpcProxy,
                       sg_rpc.SecurityGroupAgentRpcApiMixin):
    '''Agent side of the linux bridge rpc API.

    API version history:
        1.0 - Initial version.
        1.1 - Added get_active_networks_info, create_dhcp_port,
              and update_dhcp_port methods.


    '''

    BASE_RPC_API_VERSION = '1.1'

    def __init__(self, topic):
        super(AgentNotifierApi, self).__init__(
            topic=topic, default_version=self.BASE_RPC_API_VERSION)
        self.topic = topic
        self.topic_network_delete = topics.get_topic_name(topic,
                                                          topics.NETWORK,
                                                          topics.DELETE)
        self.topic_port_update = topics.get_topic_name(topic,
                                                       topics.PORT,
                                                       topics.UPDATE)

    def network_delete(self, context, network_id):
        self.fanout_cast(context,
                         self.make_msg('network_delete',
                                       network_id=network_id),
                         topic=self.topic_network_delete)

    def port_update(self, context, port, physical_network, vlan_id):
        network_type, segmentation_id = constants.interpret_vlan_id(vlan_id)
        kwargs = {'port': port,
                  'network_type': network_type,
                  'physical_network': physical_network,
                  'segmentation_id': segmentation_id}
        if cfg.CONF.AGENT.rpc_support_old_agents:
            kwargs['vlan_id'] = vlan_id
        msg = self.make_msg('port_update', **kwargs)
        self.fanout_cast(context, msg,
                         topic=self.topic_port_update)


class LinuxBridgePluginV2(db_base_plugin_v2.NeutronDbPluginV2,
                          external_net_db.External_net_db_mixin,
                          extraroute_db.ExtraRoute_db_mixin,
                          l3_gwmode_db.L3_NAT_db_mixin,
                          sg_db_rpc.SecurityGroupServerRpcMixin,
                          l3_agentschedulers_db.L3AgentSchedulerDbMixin,
                          agentschedulers_db.DhcpAgentSchedulerDbMixin,
                          portbindings_db.PortBindingMixin):
    """Implement the Neutron abstractions using Linux bridging.

    A new VLAN is created for each network.  An agent is relied upon
    to perform the actual Linux bridge configuration on each host.

    The provider extension is also supported. As discussed in
    https://bugs.launchpad.net/neutron/+bug/1023156, this class could
    be simplified, and filtering on extended attributes could be
    handled, by adding support for extended attributes to the
    NeutronDbPluginV2 base class. When that occurs, this class should
    be updated to take advantage of it.

    The port binding extension enables an external application relay
    information to and from the plugin.
    """

    # This attribute specifies whether the plugin supports or not
    # bulk/pagination/sorting operations. Name mangling is used in
    # order to ensure it is qualified by class
    __native_bulk_support = True
    __native_pagination_support = True
    __native_sorting_support = True

    _supported_extension_aliases = ["provider", "external-net", "router",
                                    "ext-gw-mode", "binding", "quotas",
                                    "security-group", "agent", "extraroute",
                                    "l3_agent_scheduler",
                                    "dhcp_agent_scheduler"]

    @property
    def supported_extension_aliases(self):
        if not hasattr(self, '_aliases'):
            aliases = self._supported_extension_aliases[:]
            sg_rpc.disable_security_group_extension_by_config(aliases)
            self._aliases = aliases
        return self._aliases

    def __init__(self):
        super(LinuxBridgePluginV2, self).__init__()
        self.base_binding_dict = {
            portbindings.VIF_TYPE: portbindings.VIF_TYPE_BRIDGE,
            portbindings.VIF_DETAILS: {
                # TODO(rkukura): Replace with new VIF security details
                portbindings.CAP_PORT_FILTER:
                'security-group' in self.supported_extension_aliases}}
        self._parse_network_vlan_ranges()
        db.sync_network_states(self.network_vlan_ranges)
        self.tenant_network_type = cfg.CONF.VLANS.tenant_network_type
        if self.tenant_network_type not in [svc_constants.TYPE_LOCAL,
                                            svc_constants.TYPE_VLAN,
                                            svc_constants.TYPE_NONE]:
            LOG.error(_("Invalid tenant_network_type: %s. "
                        "Service terminated!"),
                      self.tenant_network_type)
            sys.exit(1)
        self._setup_rpc()
        self.network_scheduler = importutils.import_object(
            cfg.CONF.network_scheduler_driver
        )
        self.router_scheduler = importutils.import_object(
            cfg.CONF.router_scheduler_driver
        )
        LOG.debug(_("Linux Bridge Plugin initialization complete"))

    def _setup_rpc(self):
        # RPC support
        self.service_topics = {svc_constants.CORE: topics.PLUGIN,
                               svc_constants.L3_ROUTER_NAT: topics.L3PLUGIN}
        self.conn = rpc.create_connection(new=True)
        self.callbacks = LinuxBridgeRpcCallbacks()
        self.dispatcher = self.callbacks.create_rpc_dispatcher()
        for svc_topic in self.service_topics.values():
            self.conn.create_consumer(svc_topic, self.dispatcher, fanout=False)
        # Consume from all consumers in a thread
        self.conn.consume_in_thread()
        self.notifier = AgentNotifierApi(topics.AGENT)
        self.agent_notifiers[q_const.AGENT_TYPE_DHCP] = (
            dhcp_rpc_agent_api.DhcpAgentNotifyAPI()
        )
        self.agent_notifiers[q_const.AGENT_TYPE_L3] = (
            l3_rpc_agent_api.L3AgentNotify
        )

    def _parse_network_vlan_ranges(self):
        try:
            self.network_vlan_ranges = plugin_utils.parse_network_vlan_ranges(
                cfg.CONF.VLANS.network_vlan_ranges)
        except Exception as ex:
            LOG.error(_("%s. Agent terminated!"), ex)
            sys.exit(1)
        LOG.info(_("Network VLAN ranges: %s"), self.network_vlan_ranges)

    def _add_network_vlan_range(self, physical_network, vlan_min, vlan_max):
        self._add_network(physical_network)
        self.network_vlan_ranges[physical_network].append((vlan_min, vlan_max))

    def _add_network(self, physical_network):
        if physical_network not in self.network_vlan_ranges:
            self.network_vlan_ranges[physical_network] = []

    def _extend_network_dict_provider(self, context, network):
        binding = db.get_network_binding(context.session, network['id'])
        if binding.vlan_id == constants.FLAT_VLAN_ID:
            network[provider.NETWORK_TYPE] = svc_constants.TYPE_FLAT
            network[provider.PHYSICAL_NETWORK] = binding.physical_network
            network[provider.SEGMENTATION_ID] = None
        elif binding.vlan_id == constants.LOCAL_VLAN_ID:
            network[provider.NETWORK_TYPE] = svc_constants.TYPE_LOCAL
            network[provider.PHYSICAL_NETWORK] = None
            network[provider.SEGMENTATION_ID] = None
        else:
            network[provider.NETWORK_TYPE] = svc_constants.TYPE_VLAN
            network[provider.PHYSICAL_NETWORK] = binding.physical_network
            network[provider.SEGMENTATION_ID] = binding.vlan_id

    def _process_provider_create(self, context, attrs):
        network_type = attrs.get(provider.NETWORK_TYPE)
        physical_network = attrs.get(provider.PHYSICAL_NETWORK)
        segmentation_id = attrs.get(provider.SEGMENTATION_ID)

        network_type_set = attributes.is_attr_set(network_type)
        physical_network_set = attributes.is_attr_set(physical_network)
        segmentation_id_set = attributes.is_attr_set(segmentation_id)

        if not (network_type_set or physical_network_set or
                segmentation_id_set):
            return (None, None, None)

        if not network_type_set:
            msg = _("provider:network_type required")
            raise n_exc.InvalidInput(error_message=msg)
        elif network_type == svc_constants.TYPE_FLAT:
            if segmentation_id_set:
                msg = _("provider:segmentation_id specified for flat network")
                raise n_exc.InvalidInput(error_message=msg)
            else:
                segmentation_id = constants.FLAT_VLAN_ID
        elif network_type == svc_constants.TYPE_VLAN:
            if not segmentation_id_set:
                msg = _("provider:segmentation_id required")
                raise n_exc.InvalidInput(error_message=msg)
            if not utils.is_valid_vlan_tag(segmentation_id):
                msg = (_("provider:segmentation_id out of range "
                         "(%(min_id)s through %(max_id)s)") %
                       {'min_id': q_const.MIN_VLAN_TAG,
                        'max_id': q_const.MAX_VLAN_TAG})
                raise n_exc.InvalidInput(error_message=msg)
        elif network_type == svc_constants.TYPE_LOCAL:
            if physical_network_set:
                msg = _("provider:physical_network specified for local "
                        "network")
                raise n_exc.InvalidInput(error_message=msg)
            else:
                physical_network = None
            if segmentation_id_set:
                msg = _("provider:segmentation_id specified for local "
                        "network")
                raise n_exc.InvalidInput(error_message=msg)
            else:
                segmentation_id = constants.LOCAL_VLAN_ID
        else:
            msg = _("provider:network_type %s not supported") % network_type
            raise n_exc.InvalidInput(error_message=msg)

        if network_type in [svc_constants.TYPE_VLAN, svc_constants.TYPE_FLAT]:
            if physical_network_set:
                if physical_network not in self.network_vlan_ranges:
                    msg = (_("Unknown provider:physical_network %s") %
                           physical_network)
                    raise n_exc.InvalidInput(error_message=msg)
            elif 'default' in self.network_vlan_ranges:
                physical_network = 'default'
            else:
                msg = _("provider:physical_network required")
                raise n_exc.InvalidInput(error_message=msg)

        return (network_type, physical_network, segmentation_id)

    def create_network(self, context, network):
        (network_type, physical_network,
         vlan_id) = self._process_provider_create(context,
                                                  network['network'])

        session = context.session
        with session.begin(subtransactions=True):
            #set up default security groups
            tenant_id = self._get_tenant_id_for_create(
                context, network['network'])
            self._ensure_default_security_group(context, tenant_id)

            if not network_type:
                # tenant network
                network_type = self.tenant_network_type
                if network_type == svc_constants.TYPE_NONE:
                    raise n_exc.TenantNetworksDisabled()
                elif network_type == svc_constants.TYPE_VLAN:
                    physical_network, vlan_id = db.reserve_network(session)
                else:  # TYPE_LOCAL
                    vlan_id = constants.LOCAL_VLAN_ID
            else:
                # provider network
                if network_type in [svc_constants.TYPE_VLAN,
                                    svc_constants.TYPE_FLAT]:
                    db.reserve_specific_network(session, physical_network,
                                                vlan_id)
                # no reservation needed for TYPE_LOCAL
            net = super(LinuxBridgePluginV2, self).create_network(context,
                                                                  network)
            db.add_network_binding(session, net['id'],
                                   physical_network, vlan_id)
            self._process_l3_create(context, net, network['network'])
            self._extend_network_dict_provider(context, net)
            # note - exception will rollback entire transaction
        return net

    def update_network(self, context, id, network):
        provider._raise_if_updates_provider_attributes(network['network'])

        session = context.session
        with session.begin(subtransactions=True):
            net = super(LinuxBridgePluginV2, self).update_network(context, id,
                                                                  network)
            self._process_l3_update(context, net, network['network'])
            self._extend_network_dict_provider(context, net)
        return net

    def delete_network(self, context, id):
        session = context.session
        with session.begin(subtransactions=True):
            binding = db.get_network_binding(session, id)
            super(LinuxBridgePluginV2, self).delete_network(context, id)
            if binding.vlan_id != constants.LOCAL_VLAN_ID:
                db.release_network(session, binding.physical_network,
                                   binding.vlan_id, self.network_vlan_ranges)
            # the network_binding record is deleted via cascade from
            # the network record, so explicit removal is not necessary
        self.notifier.network_delete(context, id)

    def get_network(self, context, id, fields=None):
        session = context.session
        with session.begin(subtransactions=True):
            net = super(LinuxBridgePluginV2, self).get_network(context,
                                                               id, None)
            self._extend_network_dict_provider(context, net)
        return self._fields(net, fields)

    def get_networks(self, context, filters=None, fields=None,
                     sorts=None, limit=None, marker=None, page_reverse=False):
        session = context.session
        with session.begin(subtransactions=True):
            nets = super(LinuxBridgePluginV2,
                         self).get_networks(context, filters, None, sorts,
                                            limit, marker, page_reverse)
            for net in nets:
                self._extend_network_dict_provider(context, net)

        return [self._fields(net, fields) for net in nets]

    def create_port(self, context, port):
        session = context.session
        port_data = port['port']
        with session.begin(subtransactions=True):
            self._ensure_default_security_group_on_port(context, port)
            sgids = self._get_security_groups_on_port(context, port)
            # Set port status as 'DOWN'. This will be updated by agent
            port['port']['status'] = q_const.PORT_STATUS_DOWN

            port = super(LinuxBridgePluginV2,
                         self).create_port(context, port)
            self._process_portbindings_create_and_update(context,
                                                         port_data,
                                                         port)
            self._process_port_create_security_group(
                context, port, sgids)
        self.notify_security_groups_member_updated(context, port)
        return port

    def update_port(self, context, id, port):
        original_port = self.get_port(context, id)
        session = context.session
        need_port_update_notify = False

        with session.begin(subtransactions=True):
            updated_port = super(LinuxBridgePluginV2, self).update_port(
                context, id, port)
            self._process_portbindings_create_and_update(context,
                                                         port['port'],
                                                         updated_port)
            need_port_update_notify = self.update_security_group_on_port(
                context, id, port, original_port, updated_port)

        need_port_update_notify |= self.is_security_group_member_updated(
            context, original_port, updated_port)

        if original_port['admin_state_up'] != updated_port['admin_state_up']:
            need_port_update_notify = True

        if need_port_update_notify:
            self._notify_port_updated(context, updated_port)
        return updated_port

    def delete_port(self, context, id, l3_port_check=True):

        # if needed, check to see if this is a port owned by
        # and l3-router.  If so, we should prevent deletion.
        if l3_port_check:
            self.prevent_l3_port_deletion(context, id)

        session = context.session
        with session.begin(subtransactions=True):
            router_ids = self.disassociate_floatingips(
                context, id, do_notify=False)
            port = self.get_port(context, id)
            self._delete_port_security_group_bindings(context, id)
            super(LinuxBridgePluginV2, self).delete_port(context, id)

        # now that we've left db transaction, we are safe to notify
        self.notify_routers_updated(context, router_ids)
        self.notify_security_groups_member_updated(context, port)

    def _notify_port_updated(self, context, port):
        binding = db.get_network_binding(context.session,
                                         port['network_id'])
        self.notifier.port_update(context, port,
                                  binding.physical_network,
                                  binding.vlan_id)
