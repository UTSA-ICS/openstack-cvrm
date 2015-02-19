# Copyright 2013 VMware, Inc.  All rights reserved.
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
#

import sqlalchemy as sa

from neutron.db import db_base_plugin_v2
from neutron.db import l3_db
from neutron.extensions import l3
from neutron.openstack.common import log as logging


LOG = logging.getLogger(__name__)
EXTERNAL_GW_INFO = l3.EXTERNAL_GW_INFO

# Modify the Router Data Model adding the enable_snat attribute
setattr(l3_db.Router, 'enable_snat',
        sa.Column(sa.Boolean, default=True, nullable=False))


class L3_NAT_db_mixin(l3_db.L3_NAT_db_mixin):
    """Mixin class to add configurable gateway modes."""

    # Register dict extend functions for ports and networks
    db_base_plugin_v2.NeutronDbPluginV2.register_dict_extend_funcs(
        l3.ROUTERS, ['_extend_router_dict_gw_mode'])

    def _extend_router_dict_gw_mode(self, router_res, router_db):
        if router_db.gw_port_id:
            nw_id = router_db.gw_port['network_id']
            router_res[EXTERNAL_GW_INFO] = {
                'network_id': nw_id,
                'enable_snat': router_db.enable_snat}

    def _update_router_gw_info(self, context, router_id, info, router=None):
        # Load the router only if necessary
        if not router:
            router = self._get_router(context, router_id)
        # if enable_snat is not specified use the value
        # stored in the database (default:True)
        enable_snat = not info or info.get('enable_snat', router.enable_snat)
        with context.session.begin(subtransactions=True):
            router.enable_snat = enable_snat

        # Calls superclass, pass router db object for avoiding re-loading
        super(L3_NAT_db_mixin, self)._update_router_gw_info(
            context, router_id, info, router=router)
        # Returning the router might come back useful if this
        # method is overriden in child classes
        return router

    def _build_routers_list(self, routers, gw_ports):
        gw_port_id_gw_port_dict = {}
        for gw_port in gw_ports:
            gw_port_id_gw_port_dict[gw_port['id']] = gw_port
        for rtr in routers:
            gw_port_id = rtr['gw_port_id']
            if gw_port_id:
                rtr['gw_port'] = gw_port_id_gw_port_dict[gw_port_id]
                # Add enable_snat key
                rtr['enable_snat'] = rtr[EXTERNAL_GW_INFO]['enable_snat']
        return routers
