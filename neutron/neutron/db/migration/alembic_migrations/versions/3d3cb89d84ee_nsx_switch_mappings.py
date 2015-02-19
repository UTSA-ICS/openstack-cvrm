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

"""nsx_switch_mappings

Revision ID: 3d3cb89d84ee
Revises: 1421183d533f
Create Date: 2014-01-07 15:37:41.323020

"""

# revision identifiers, used by Alembic.
revision = '3d3cb89d84ee'
down_revision = '1421183d533f'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = [
    'neutron.plugins.nicira.NeutronPlugin.NvpPluginV2',
    'neutron.plugins.nicira.NeutronServicePlugin.NvpAdvancedPlugin',
    'neutron.plugins.vmware.plugin.NsxPlugin',
    'neutron.plugins.vmware.plugin.NsxServicePlugin'
]

from alembic import op
import sqlalchemy as sa

from neutron.db import migration


def upgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    # Create table for network mappings
    op.create_table(
        'neutron_nsx_network_mappings',
        sa.Column('neutron_id', sa.String(length=36), nullable=False),
        sa.Column('nsx_id', sa.String(length=36), nullable=True),
        sa.ForeignKeyConstraint(['neutron_id'], ['networks.id'],
                                ondelete='CASCADE'),
        # There might be multiple switches for a neutron network
        sa.PrimaryKeyConstraint('neutron_id', 'nsx_id'),
    )


def downgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    op.drop_table('neutron_nsx_network_mappings')
