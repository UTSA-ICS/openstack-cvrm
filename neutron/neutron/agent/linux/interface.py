# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import abc

import netaddr
from oslo.config import cfg
import six

from neutron.agent.common import config
from neutron.agent.linux import ip_lib
from neutron.agent.linux import ovs_lib
from neutron.agent.linux import utils
from neutron.common import exceptions
from neutron.extensions.flavor import (FLAVOR_NETWORK)
from neutron.openstack.common import importutils
from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)

OPTS = [
    cfg.StrOpt('ovs_integration_bridge',
               default='br-int',
               help=_('Name of Open vSwitch bridge to use')),
    cfg.BoolOpt('ovs_use_veth',
                default=False,
                help=_('Uses veth for an interface or not')),
    cfg.IntOpt('network_device_mtu',
               help=_('MTU setting for device.')),
    cfg.StrOpt('meta_flavor_driver_mappings',
               help=_('Mapping between flavor and LinuxInterfaceDriver')),
    cfg.StrOpt('admin_user',
               help=_("Admin username")),
    cfg.StrOpt('admin_password',
               help=_("Admin password"),
               secret=True),
    cfg.StrOpt('admin_tenant_name',
               help=_("Admin tenant name")),
    cfg.StrOpt('auth_url',
               help=_("Authentication URL")),
    cfg.StrOpt('auth_strategy', default='keystone',
               help=_("The type of authentication to use")),
    cfg.StrOpt('auth_region',
               help=_("Authentication region")),
]


@six.add_metaclass(abc.ABCMeta)
class LinuxInterfaceDriver(object):

    # from linux IF_NAMESIZE
    DEV_NAME_LEN = 14
    DEV_NAME_PREFIX = 'tap'

    def __init__(self, conf):
        self.conf = conf
        self.root_helper = config.get_root_helper(conf)

    def init_l3(self, device_name, ip_cidrs, namespace=None,
                preserve_ips=[]):
        """Set the L3 settings for the interface using data from the port.

        ip_cidrs: list of 'X.X.X.X/YY' strings
        preserve_ips: list of ip cidrs that should not be removed from device
        """
        device = ip_lib.IPDevice(device_name,
                                 self.root_helper,
                                 namespace=namespace)

        previous = {}
        for address in device.addr.list(scope='global', filters=['permanent']):
            previous[address['cidr']] = address['ip_version']

        # add new addresses
        for ip_cidr in ip_cidrs:

            net = netaddr.IPNetwork(ip_cidr)
            if ip_cidr in previous:
                del previous[ip_cidr]
                continue

            device.addr.add(net.version, ip_cidr, str(net.broadcast))

        # clean up any old addresses
        for ip_cidr, ip_version in previous.items():
            if ip_cidr not in preserve_ips:
                device.addr.delete(ip_version, ip_cidr)

    def check_bridge_exists(self, bridge):
        if not ip_lib.device_exists(bridge):
            raise exceptions.BridgeDoesNotExist(bridge=bridge)

    def get_device_name(self, port):
        return (self.DEV_NAME_PREFIX + port.id)[:self.DEV_NAME_LEN]

    @abc.abstractmethod
    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """Plug in the interface."""

    @abc.abstractmethod
    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""


class NullDriver(LinuxInterfaceDriver):
    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        pass

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        pass


class OVSInterfaceDriver(LinuxInterfaceDriver):
    """Driver for creating an internal interface on an OVS bridge."""

    DEV_NAME_PREFIX = 'tap'

    def __init__(self, conf):
        super(OVSInterfaceDriver, self).__init__(conf)
        if self.conf.ovs_use_veth:
            self.DEV_NAME_PREFIX = 'ns-'

    def _get_tap_name(self, dev_name, prefix=None):
        if self.conf.ovs_use_veth:
            dev_name = dev_name.replace(prefix or self.DEV_NAME_PREFIX, 'tap')
        return dev_name

    def _ovs_add_port(self, bridge, device_name, port_id, mac_address,
                      internal=True):
        cmd = ['ovs-vsctl', '--', '--if-exists', 'del-port', device_name, '--',
               'add-port', bridge, device_name]
        if internal:
            cmd += ['--', 'set', 'Interface', device_name, 'type=internal']
        cmd += ['--', 'set', 'Interface', device_name,
                'external-ids:iface-id=%s' % port_id,
                '--', 'set', 'Interface', device_name,
                'external-ids:iface-status=active',
                '--', 'set', 'Interface', device_name,
                'external-ids:attached-mac=%s' % mac_address]
        utils.execute(cmd, self.root_helper)

    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """Plug in the interface."""
        if not bridge:
            bridge = self.conf.ovs_integration_bridge

        if not ip_lib.device_exists(device_name,
                                    self.root_helper,
                                    namespace=namespace):

            self.check_bridge_exists(bridge)

            ip = ip_lib.IPWrapper(self.root_helper)
            tap_name = self._get_tap_name(device_name, prefix)

            if self.conf.ovs_use_veth:
                # Create ns_dev in a namespace if one is configured.
                root_dev, ns_dev = ip.add_veth(tap_name,
                                               device_name,
                                               namespace2=namespace)
            else:
                ns_dev = ip.device(device_name)

            internal = not self.conf.ovs_use_veth
            self._ovs_add_port(bridge, tap_name, port_id, mac_address,
                               internal=internal)

            ns_dev.link.set_address(mac_address)

            if self.conf.network_device_mtu:
                ns_dev.link.set_mtu(self.conf.network_device_mtu)
                if self.conf.ovs_use_veth:
                    root_dev.link.set_mtu(self.conf.network_device_mtu)

            # Add an interface created by ovs to the namespace.
            if not self.conf.ovs_use_veth and namespace:
                namespace_obj = ip.ensure_namespace(namespace)
                namespace_obj.add_device_to_namespace(ns_dev)

            ns_dev.link.set_up()
            if self.conf.ovs_use_veth:
                root_dev.link.set_up()
        else:
            LOG.info(_("Device %s already exists"), device_name)

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""
        if not bridge:
            bridge = self.conf.ovs_integration_bridge

        tap_name = self._get_tap_name(device_name, prefix)
        self.check_bridge_exists(bridge)
        ovs = ovs_lib.OVSBridge(bridge, self.root_helper)

        try:
            ovs.delete_port(tap_name)
            if self.conf.ovs_use_veth:
                device = ip_lib.IPDevice(device_name,
                                         self.root_helper,
                                         namespace)
                device.link.delete()
                LOG.debug(_("Unplugged interface '%s'"), device_name)
        except RuntimeError:
            LOG.error(_("Failed unplugging interface '%s'"),
                      device_name)


class MidonetInterfaceDriver(LinuxInterfaceDriver):

    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """This method is called by the Dhcp agent or by the L3 agent
        when a new network is created
        """
        if not ip_lib.device_exists(device_name,
                                    self.root_helper,
                                    namespace=namespace):
            ip = ip_lib.IPWrapper(self.root_helper)
            tap_name = device_name.replace(prefix or 'tap', 'tap')

            # Create ns_dev in a namespace if one is configured.
            root_dev, ns_dev = ip.add_veth(tap_name, device_name,
                                           namespace2=namespace)

            ns_dev.link.set_address(mac_address)

            # Add an interface created by ovs to the namespace.
            namespace_obj = ip.ensure_namespace(namespace)
            namespace_obj.add_device_to_namespace(ns_dev)

            ns_dev.link.set_up()
            root_dev.link.set_up()

            cmd = ['mm-ctl', '--bind-port', port_id, device_name]
            utils.execute(cmd, self.root_helper)

        else:
            LOG.info(_("Device %s already exists"), device_name)

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        # the port will be deleted by the dhcp agent that will call the plugin
        device = ip_lib.IPDevice(device_name,
                                 self.root_helper,
                                 namespace)
        try:
            device.link.delete()
        except RuntimeError:
            LOG.error(_("Failed unplugging interface '%s'"), device_name)
        LOG.debug(_("Unplugged interface '%s'"), device_name)

        ip_lib.IPWrapper(
            self.root_helper, namespace).garbage_collect_namespace()


class IVSInterfaceDriver(LinuxInterfaceDriver):
    """Driver for creating an internal interface on an IVS bridge."""

    DEV_NAME_PREFIX = 'tap'

    def __init__(self, conf):
        super(IVSInterfaceDriver, self).__init__(conf)
        self.DEV_NAME_PREFIX = 'ns-'

    def _get_tap_name(self, dev_name, prefix=None):
        dev_name = dev_name.replace(prefix or self.DEV_NAME_PREFIX, 'tap')
        return dev_name

    def _ivs_add_port(self, device_name, port_id, mac_address):
        cmd = ['ivs-ctl', 'add-port', device_name]
        utils.execute(cmd, self.root_helper)

    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """Plug in the interface."""
        if not ip_lib.device_exists(device_name,
                                    self.root_helper,
                                    namespace=namespace):

            ip = ip_lib.IPWrapper(self.root_helper)
            tap_name = self._get_tap_name(device_name, prefix)

            root_dev, ns_dev = ip.add_veth(tap_name, device_name)

            self._ivs_add_port(tap_name, port_id, mac_address)

            ns_dev = ip.device(device_name)
            ns_dev.link.set_address(mac_address)

            if self.conf.network_device_mtu:
                ns_dev.link.set_mtu(self.conf.network_device_mtu)
                root_dev.link.set_mtu(self.conf.network_device_mtu)

            if namespace:
                namespace_obj = ip.ensure_namespace(namespace)
                namespace_obj.add_device_to_namespace(ns_dev)

            ns_dev.link.set_up()
            root_dev.link.set_up()
        else:
            LOG.info(_("Device %s already exists"), device_name)

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""
        tap_name = self._get_tap_name(device_name, prefix)
        try:
            cmd = ['ivs-ctl', 'del-port', tap_name]
            utils.execute(cmd, self.root_helper)
            device = ip_lib.IPDevice(device_name,
                                     self.root_helper,
                                     namespace)
            device.link.delete()
            LOG.debug(_("Unplugged interface '%s'"), device_name)
        except RuntimeError:
            LOG.error(_("Failed unplugging interface '%s'"),
                      device_name)


class BridgeInterfaceDriver(LinuxInterfaceDriver):
    """Driver for creating bridge interfaces."""

    DEV_NAME_PREFIX = 'ns-'

    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        """Plugin the interface."""
        if not ip_lib.device_exists(device_name,
                                    self.root_helper,
                                    namespace=namespace):
            ip = ip_lib.IPWrapper(self.root_helper)

            # Enable agent to define the prefix
            if prefix:
                tap_name = device_name.replace(prefix, 'tap')
            else:
                tap_name = device_name.replace(self.DEV_NAME_PREFIX, 'tap')
            # Create ns_veth in a namespace if one is configured.
            root_veth, ns_veth = ip.add_veth(tap_name, device_name,
                                             namespace2=namespace)
            ns_veth.link.set_address(mac_address)

            if self.conf.network_device_mtu:
                root_veth.link.set_mtu(self.conf.network_device_mtu)
                ns_veth.link.set_mtu(self.conf.network_device_mtu)

            root_veth.link.set_up()
            ns_veth.link.set_up()

        else:
            LOG.info(_("Device %s already exists"), device_name)

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        """Unplug the interface."""
        device = ip_lib.IPDevice(device_name, self.root_helper, namespace)
        try:
            device.link.delete()
            LOG.debug(_("Unplugged interface '%s'"), device_name)
        except RuntimeError:
            LOG.error(_("Failed unplugging interface '%s'"),
                      device_name)


class MetaInterfaceDriver(LinuxInterfaceDriver):
    def __init__(self, conf):
        super(MetaInterfaceDriver, self).__init__(conf)
        from neutronclient.v2_0 import client
        self.neutron = client.Client(
            username=self.conf.admin_user,
            password=self.conf.admin_password,
            tenant_name=self.conf.admin_tenant_name,
            auth_url=self.conf.auth_url,
            auth_strategy=self.conf.auth_strategy,
            region_name=self.conf.auth_region
        )
        self.flavor_driver_map = {}
        for flavor, driver_name in [
                driver_set.split(':')
                for driver_set in
                self.conf.meta_flavor_driver_mappings.split(',')]:
            self.flavor_driver_map[flavor] = self._load_driver(driver_name)

    def _get_flavor_by_network_id(self, network_id):
        network = self.neutron.show_network(network_id)
        return network['network'][FLAVOR_NETWORK]

    def _get_driver_by_network_id(self, network_id):
        flavor = self._get_flavor_by_network_id(network_id)
        return self.flavor_driver_map[flavor]

    def _set_device_plugin_tag(self, network_id, device_name, namespace=None):
        plugin_tag = self._get_flavor_by_network_id(network_id)
        device = ip_lib.IPDevice(device_name, self.conf.root_helper, namespace)
        device.link.set_alias(plugin_tag)

    def _get_device_plugin_tag(self, device_name, namespace=None):
        device = ip_lib.IPDevice(device_name, self.conf.root_helper, namespace)
        return device.link.alias

    def get_device_name(self, port):
        driver = self._get_driver_by_network_id(port.network_id)
        return driver.get_device_name(port)

    def plug(self, network_id, port_id, device_name, mac_address,
             bridge=None, namespace=None, prefix=None):
        driver = self._get_driver_by_network_id(network_id)
        ret = driver.plug(network_id, port_id, device_name, mac_address,
                          bridge=bridge, namespace=namespace, prefix=prefix)
        self._set_device_plugin_tag(network_id, device_name, namespace)
        return ret

    def unplug(self, device_name, bridge=None, namespace=None, prefix=None):
        plugin_tag = self._get_device_plugin_tag(device_name, namespace)
        driver = self.flavor_driver_map[plugin_tag]
        return driver.unplug(device_name, bridge, namespace, prefix)

    def _load_driver(self, driver_provider):
        LOG.debug(_("Driver location: %s"), driver_provider)
        plugin_klass = importutils.import_class(driver_provider)
        return plugin_klass(self.conf)
