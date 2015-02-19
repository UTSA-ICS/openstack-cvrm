# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation.
# All rights reserved.
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

from abc import abstractmethod

from neutron.api import extensions
from neutron.api.v2 import base
from neutron.api.v2 import resource
from neutron.common import constants
from neutron.common import exceptions
from neutron.extensions import agent
from neutron import manager
from neutron import policy
from neutron import wsgi

DHCP_NET = 'dhcp-network'
DHCP_NETS = DHCP_NET + 's'
DHCP_AGENT = 'dhcp-agent'
DHCP_AGENTS = DHCP_AGENT + 's'


class NetworkSchedulerController(wsgi.Controller):
    def index(self, request, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "get_%s" % DHCP_NETS,
                       {})
        return plugin.list_networks_on_dhcp_agent(
            request.context, kwargs['agent_id'])

    def create(self, request, body, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "create_%s" % DHCP_NET,
                       {})
        return plugin.add_network_to_dhcp_agent(
            request.context, kwargs['agent_id'], body['network_id'])

    def delete(self, request, id, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "delete_%s" % DHCP_NET,
                       {})
        return plugin.remove_network_from_dhcp_agent(
            request.context, kwargs['agent_id'], id)


class DhcpAgentsHostingNetworkController(wsgi.Controller):
    def index(self, request, **kwargs):
        plugin = manager.NeutronManager.get_plugin()
        policy.enforce(request.context,
                       "get_%s" % DHCP_AGENTS,
                       {})
        return plugin.list_dhcp_agents_hosting_network(
            request.context, kwargs['network_id'])


class Dhcpagentscheduler(extensions.ExtensionDescriptor):
    """Extension class supporting dhcp agent scheduler.
    """

    @classmethod
    def get_name(cls):
        return "DHCP Agent Scheduler"

    @classmethod
    def get_alias(cls):
        return constants.DHCP_AGENT_SCHEDULER_EXT_ALIAS

    @classmethod
    def get_description(cls):
        return "Schedule networks among dhcp agents"

    @classmethod
    def get_namespace(cls):
        return "http://docs.openstack.org/ext/dhcp_agent_scheduler/api/v1.0"

    @classmethod
    def get_updated(cls):
        return "2013-02-07T10:00:00-00:00"

    @classmethod
    def get_resources(cls):
        """Returns Ext Resources."""
        exts = []
        parent = dict(member_name="agent",
                      collection_name="agents")
        controller = resource.Resource(NetworkSchedulerController(),
                                       base.FAULT_MAP)
        exts.append(extensions.ResourceExtension(
            DHCP_NETS, controller, parent))

        parent = dict(member_name="network",
                      collection_name="networks")

        controller = resource.Resource(DhcpAgentsHostingNetworkController(),
                                       base.FAULT_MAP)
        exts.append(extensions.ResourceExtension(
            DHCP_AGENTS, controller, parent))
        return exts

    def get_extended_resources(self, version):
        return {}


class InvalidDHCPAgent(agent.AgentNotFound):
    message = _("Agent %(id)s is not a valid DHCP Agent or has been disabled")


class NetworkHostedByDHCPAgent(exceptions.Conflict):
    message = _("The network %(network_id)s has been already hosted"
                " by the DHCP Agent %(agent_id)s.")


class NetworkNotHostedByDhcpAgent(exceptions.Conflict):
    message = _("The network %(network_id)s is not hosted"
                " by the DHCP agent %(agent_id)s.")


class DhcpAgentSchedulerPluginBase(object):
    """REST API to operate the DHCP agent scheduler.

    All of method must be in an admin context.
    """

    @abstractmethod
    def add_network_to_dhcp_agent(self, context, id, network_id):
        pass

    @abstractmethod
    def remove_network_from_dhcp_agent(self, context, id, network_id):
        pass

    @abstractmethod
    def list_networks_on_dhcp_agent(self, context, id):
        pass

    @abstractmethod
    def list_dhcp_agents_hosting_network(self, context, network_id):
        pass
