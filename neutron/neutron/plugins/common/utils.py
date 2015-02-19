# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Cisco Systems, Inc.
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

"""
Common utilities and helper functions for Openstack Networking Plugins.
"""

from neutron.common import exceptions as n_exc
from neutron.common import utils
from neutron.plugins.common import constants


def verify_vlan_range(vlan_range):
    """Raise an exception for invalid tags or malformed range."""
    for vlan_tag in vlan_range:
        if not utils.is_valid_vlan_tag(vlan_tag):
            raise n_exc.NetworkVlanRangeError(
                vlan_range=vlan_range,
                error=_("%s is not a valid VLAN tag") % vlan_tag)
    if vlan_range[1] < vlan_range[0]:
        raise n_exc.NetworkVlanRangeError(
            vlan_range=vlan_range,
            error=_("End of VLAN range is less than start of VLAN range"))


def parse_network_vlan_range(network_vlan_range):
    """Interpret a string as network[:vlan_begin:vlan_end]."""
    entry = network_vlan_range.strip()
    if ':' in entry:
        try:
            network, vlan_min, vlan_max = entry.split(':')
            vlan_range = (int(vlan_min), int(vlan_max))
        except ValueError as ex:
            raise n_exc.NetworkVlanRangeError(vlan_range=entry, error=ex)
        verify_vlan_range(vlan_range)
        return network, vlan_range
    else:
        return entry, None


def parse_network_vlan_ranges(network_vlan_ranges_cfg_entries):
    """Interpret a list of strings as network[:vlan_begin:vlan_end] entries."""
    networks = {}
    for entry in network_vlan_ranges_cfg_entries:
        network, vlan_range = parse_network_vlan_range(entry)
        if vlan_range:
            networks.setdefault(network, []).append(vlan_range)
        else:
            networks.setdefault(network, [])
    return networks


def in_pending_status(status):
    return status in (constants.PENDING_CREATE,
                      constants.PENDING_UPDATE,
                      constants.PENDING_DELETE)
