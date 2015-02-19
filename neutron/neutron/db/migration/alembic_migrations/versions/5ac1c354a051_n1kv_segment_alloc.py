# Copyright 2014 OpenStack Foundation
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

"""n1kv segment allocs for cisco n1kv plugin

Revision ID: 5ac1c354a051
Revises: 538732fa21e1
Create Date: 2014-03-05 17:36:52.952608

"""

# revision identifiers, used by Alembic.
revision = '5ac1c354a051'
down_revision = '538732fa21e1'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = [
    'neutron.plugins.cisco.network_plugin.PluginV2'
]

from alembic import op
import sqlalchemy as sa

from neutron.db import migration


def upgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    op.add_column(
        'cisco_n1kv_vlan_allocations',
        sa.Column('network_profile_id',
                  sa.String(length=36),
                  nullable=False)
    )
    op.create_foreign_key(
        'cisco_n1kv_vlan_allocations_ibfk_1',
        source='cisco_n1kv_vlan_allocations',
        referent='cisco_network_profiles',
        local_cols=['network_profile_id'], remote_cols=['id'],
        ondelete='CASCADE'
    )
    op.add_column(
        'cisco_n1kv_vxlan_allocations',
        sa.Column('network_profile_id',
                  sa.String(length=36),
                  nullable=False)
    )
    op.create_foreign_key(
        'cisco_n1kv_vxlan_allocations_ibfk_1',
        source='cisco_n1kv_vxlan_allocations',
        referent='cisco_network_profiles',
        local_cols=['network_profile_id'], remote_cols=['id'],
        ondelete='CASCADE'
    )


def downgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    op.drop_constraint('cisco_n1kv_vxlan_allocations_ibfk_1',
                       'cisco_n1kv_vxlan_allocations',
                       'foreignkey')
    op.drop_column('cisco_n1kv_vxlan_allocations', 'network_profile_id')
    op.drop_constraint('cisco_n1kv_vlan_allocations_ibfk_1',
                       'cisco_n1kv_vlan_allocations',
                       'foreignkey')
    op.drop_column('cisco_n1kv_vlan_allocations', 'network_profile_id')
