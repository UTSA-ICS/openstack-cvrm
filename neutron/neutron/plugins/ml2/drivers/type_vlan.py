# Copyright (c) 2013 OpenStack Foundation
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

import sys

from oslo.config import cfg
from six.moves import xrange
import sqlalchemy as sa

from neutron.common import constants as q_const
from neutron.common import exceptions as exc
from neutron.common import utils
from neutron.db import api as db_api
from neutron.db import model_base
from neutron.openstack.common import log
from neutron.plugins.common import constants as p_const
from neutron.plugins.common import utils as plugin_utils
from neutron.plugins.ml2 import driver_api as api

LOG = log.getLogger(__name__)

vlan_opts = [
    cfg.ListOpt('network_vlan_ranges',
                default=[],
                help=_("List of <physical_network>:<vlan_min>:<vlan_max> or "
                       "<physical_network> specifying physical_network names "
                       "usable for VLAN provider and tenant networks, as "
                       "well as ranges of VLAN tags on each available for "
                       "allocation to tenant networks."))
]

cfg.CONF.register_opts(vlan_opts, "ml2_type_vlan")


class VlanAllocation(model_base.BASEV2):
    """Represent allocation state of a vlan_id on a physical network.

    If allocated is False, the vlan_id on the physical_network is
    available for allocation to a tenant network. If allocated is
    True, the vlan_id on the physical_network is in use, either as a
    tenant or provider network.

    When an allocation is released, if the vlan_id for the
    physical_network is inside the pool described by
    VlanTypeDriver.network_vlan_ranges, then allocated is set to
    False. If it is outside the pool, the record is deleted.
    """

    __tablename__ = 'ml2_vlan_allocations'

    physical_network = sa.Column(sa.String(64), nullable=False,
                                 primary_key=True)
    vlan_id = sa.Column(sa.Integer, nullable=False, primary_key=True,
                        autoincrement=False)
    allocated = sa.Column(sa.Boolean, nullable=False)


class VlanTypeDriver(api.TypeDriver):
    """Manage state for VLAN networks with ML2.

    The VlanTypeDriver implements the 'vlan' network_type. VLAN
    network segments provide connectivity between VMs and other
    devices using any connected IEEE 802.1Q conformant
    physical_network segmented into virtual networks via IEEE 802.1Q
    headers. Up to 4094 VLAN network segments can exist on each
    available physical_network.
    """

    def __init__(self):
        self._parse_network_vlan_ranges()

    def _parse_network_vlan_ranges(self):
        try:
            self.network_vlan_ranges = plugin_utils.parse_network_vlan_ranges(
                cfg.CONF.ml2_type_vlan.network_vlan_ranges)
            # TODO(rkukura): Validate that each physical_network name
            # is neither empty nor too long.
        except Exception:
            LOG.exception(_("Failed to parse network_vlan_ranges. "
                            "Service terminated!"))
            sys.exit(1)
        LOG.info(_("Network VLAN ranges: %s"), self.network_vlan_ranges)

    def _sync_vlan_allocations(self):
        session = db_api.get_session()
        with session.begin(subtransactions=True):
            # get existing allocations for all physical networks
            allocations = dict()
            allocs = (session.query(VlanAllocation).
                      with_lockmode('update'))
            for alloc in allocs:
                if alloc.physical_network not in allocations:
                    allocations[alloc.physical_network] = set()
                allocations[alloc.physical_network].add(alloc)

            # process vlan ranges for each configured physical network
            for (physical_network,
                 vlan_ranges) in self.network_vlan_ranges.items():
                # determine current configured allocatable vlans for
                # this physical network
                vlan_ids = set()
                for vlan_min, vlan_max in vlan_ranges:
                    vlan_ids |= set(xrange(vlan_min, vlan_max + 1))

                # remove from table unallocated vlans not currently
                # allocatable
                if physical_network in allocations:
                    for alloc in allocations[physical_network]:
                        try:
                            # see if vlan is allocatable
                            vlan_ids.remove(alloc.vlan_id)
                        except KeyError:
                            # it's not allocatable, so check if its allocated
                            if not alloc.allocated:
                                # it's not, so remove it from table
                                LOG.debug(_("Removing vlan %(vlan_id)s on "
                                            "physical network "
                                            "%(physical_network)s from pool"),
                                          {'vlan_id': alloc.vlan_id,
                                           'physical_network':
                                           physical_network})
                                session.delete(alloc)
                    del allocations[physical_network]

                # add missing allocatable vlans to table
                for vlan_id in sorted(vlan_ids):
                    alloc = VlanAllocation(physical_network=physical_network,
                                           vlan_id=vlan_id,
                                           allocated=False)
                    session.add(alloc)

            # remove from table unallocated vlans for any unconfigured
            # physical networks
            for allocs in allocations.itervalues():
                for alloc in allocs:
                    if not alloc.allocated:
                        LOG.debug(_("Removing vlan %(vlan_id)s on physical "
                                    "network %(physical_network)s from pool"),
                                  {'vlan_id': alloc.vlan_id,
                                   'physical_network':
                                   alloc.physical_network})
                        session.delete(alloc)

    def get_type(self):
        return p_const.TYPE_VLAN

    def initialize(self):
        self._sync_vlan_allocations()
        LOG.info(_("VlanTypeDriver initialization complete"))

    def validate_provider_segment(self, segment):
        physical_network = segment.get(api.PHYSICAL_NETWORK)
        if not physical_network:
            msg = _("physical_network required for VLAN provider network")
            raise exc.InvalidInput(error_message=msg)
        if physical_network not in self.network_vlan_ranges:
            msg = (_("physical_network '%s' unknown for VLAN provider network")
                   % physical_network)
            raise exc.InvalidInput(error_message=msg)

        segmentation_id = segment.get(api.SEGMENTATION_ID)
        if segmentation_id is None:
            msg = _("segmentation_id required for VLAN provider network")
            raise exc.InvalidInput(error_message=msg)
        if not utils.is_valid_vlan_tag(segmentation_id):
            msg = (_("segmentation_id out of range (%(min)s through "
                     "%(max)s)") %
                   {'min': q_const.MIN_VLAN_TAG,
                    'max': q_const.MAX_VLAN_TAG})
            raise exc.InvalidInput(error_message=msg)

        for key, value in segment.items():
            if value and key not in [api.NETWORK_TYPE,
                                     api.PHYSICAL_NETWORK,
                                     api.SEGMENTATION_ID]:
                msg = _("%s prohibited for VLAN provider network") % key
                raise exc.InvalidInput(error_message=msg)

    def reserve_provider_segment(self, session, segment):
        physical_network = segment[api.PHYSICAL_NETWORK]
        vlan_id = segment[api.SEGMENTATION_ID]
        with session.begin(subtransactions=True):
            try:
                alloc = (session.query(VlanAllocation).
                         filter_by(physical_network=physical_network,
                                   vlan_id=vlan_id).
                         with_lockmode('update').
                         one())
                if alloc.allocated:
                    raise exc.VlanIdInUse(vlan_id=vlan_id,
                                          physical_network=physical_network)
                LOG.debug(_("Reserving specific vlan %(vlan_id)s on physical "
                            "network %(physical_network)s from pool"),
                          {'vlan_id': vlan_id,
                           'physical_network': physical_network})
                alloc.allocated = True
            except sa.orm.exc.NoResultFound:
                LOG.debug(_("Reserving specific vlan %(vlan_id)s on physical "
                            "network %(physical_network)s outside pool"),
                          {'vlan_id': vlan_id,
                           'physical_network': physical_network})
                alloc = VlanAllocation(physical_network=physical_network,
                                       vlan_id=vlan_id,
                                       allocated=True)
                session.add(alloc)

    def allocate_tenant_segment(self, session):
        with session.begin(subtransactions=True):
            alloc = (session.query(VlanAllocation).
                     filter_by(allocated=False).
                     with_lockmode('update').
                     first())
            if alloc:
                LOG.debug(_("Allocating vlan %(vlan_id)s on physical network "
                            "%(physical_network)s from pool"),
                          {'vlan_id': alloc.vlan_id,
                           'physical_network': alloc.physical_network})
                alloc.allocated = True
                return {api.NETWORK_TYPE: p_const.TYPE_VLAN,
                        api.PHYSICAL_NETWORK: alloc.physical_network,
                        api.SEGMENTATION_ID: alloc.vlan_id}

    def release_segment(self, session, segment):
        physical_network = segment[api.PHYSICAL_NETWORK]
        vlan_id = segment[api.SEGMENTATION_ID]
        with session.begin(subtransactions=True):
            try:
                alloc = (session.query(VlanAllocation).
                         filter_by(physical_network=physical_network,
                                   vlan_id=vlan_id).
                         with_lockmode('update').
                         one())
                alloc.allocated = False
                inside = False
                for vlan_min, vlan_max in self.network_vlan_ranges.get(
                    physical_network, []):
                    if vlan_min <= vlan_id <= vlan_max:
                        inside = True
                        break
                if not inside:
                    session.delete(alloc)
                    LOG.debug(_("Releasing vlan %(vlan_id)s on physical "
                                "network %(physical_network)s outside pool"),
                              {'vlan_id': vlan_id,
                               'physical_network': physical_network})
                else:
                    LOG.debug(_("Releasing vlan %(vlan_id)s on physical "
                                "network %(physical_network)s to pool"),
                              {'vlan_id': vlan_id,
                               'physical_network': physical_network})
            except sa.orm.exc.NoResultFound:
                LOG.warning(_("No vlan_id %(vlan_id)s found on physical "
                              "network %(physical_network)s"),
                            {'vlan_id': vlan_id,
                             'physical_network': physical_network})
