# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack Foundation.
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

from oslo.config import cfg

from neutron.agent.common import config as agent_config
from neutron.agent import l3_agent
from neutron.agent.linux import interface
from neutron.agent.linux import ip_lib
from neutron.agent.linux import ovs_lib
from neutron.common import config
from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)


def setup_conf():
    """Setup the cfg for the clean up utility.

    Use separate setup_conf for the utility because there are many options
    from the main config that do not apply during clean-up.
    """
    opts = [
        cfg.BoolOpt('ovs_all_ports',
                    default=False,
                    help=_('True to delete all ports on all the OpenvSwitch '
                           'bridges. False to delete ports created by '
                           'Neutron on integration and external network '
                           'bridges.'))
    ]

    conf = cfg.CONF
    conf.register_cli_opts(opts)
    conf.register_opts(l3_agent.L3NATAgent.OPTS)
    conf.register_opts(interface.OPTS)
    agent_config.register_interface_driver_opts_helper(conf)
    agent_config.register_use_namespaces_opts_helper(conf)
    agent_config.register_root_helper(conf)
    return conf


def collect_neutron_ports(bridges, root_helper):
    """Collect ports created by Neutron from OVS."""
    ports = []
    for bridge in bridges:
        ovs = ovs_lib.OVSBridge(bridge, root_helper)
        ports += [port.port_name for port in ovs.get_vif_ports()]
    return ports


def delete_neutron_ports(ports, root_helper):
    """Delete non-internal ports created by Neutron

    Non-internal OVS ports need to be removed manually.
    """
    for port in ports:
        if ip_lib.device_exists(port):
            device = ip_lib.IPDevice(port, root_helper)
            device.link.delete()
            LOG.info(_("Delete %s"), port)


def main():
    """Main method for cleaning up OVS bridges.

    The utility cleans up the integration bridges used by Neutron.
    """

    conf = setup_conf()
    conf()
    config.setup_logging(conf)

    configuration_bridges = set([conf.ovs_integration_bridge,
                                 conf.external_network_bridge])
    ovs_bridges = set(ovs_lib.get_bridges(conf.AGENT.root_helper))
    available_configuration_bridges = configuration_bridges & ovs_bridges

    if conf.ovs_all_ports:
        bridges = ovs_bridges
    else:
        bridges = available_configuration_bridges

    # Collect existing ports created by Neutron on configuration bridges.
    # After deleting ports from OVS bridges, we cannot determine which
    # ports were created by Neutron, so port information is collected now.
    ports = collect_neutron_ports(available_configuration_bridges,
                                  conf.AGENT.root_helper)

    for bridge in bridges:
        LOG.info(_("Cleaning %s"), bridge)
        ovs = ovs_lib.OVSBridge(bridge, conf.AGENT.root_helper)
        ovs.delete_ports(all_ports=conf.ovs_all_ports)

    # Remove remaining ports created by Neutron (usually veth pair)
    delete_neutron_ports(ports, conf.AGENT.root_helper)

    LOG.info(_("OVS cleanup completed successfully"))
