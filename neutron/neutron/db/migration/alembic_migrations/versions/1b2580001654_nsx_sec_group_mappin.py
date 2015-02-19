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

"""nsx_sec_group_mapping

Revision ID: 1b2580001654
Revises: abc88c33f74f
Create Date: 2013-12-27 13:02:42.894648

"""

# revision identifiers, used by Alembic.
revision = '1b2580001654'
down_revision = 'abc88c33f74f'

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
    # Create table for security group mappings
    op.create_table(
        'neutron_nsx_security_group_mappings',
        sa.Column('neutron_id', sa.String(length=36), nullable=False),
        sa.Column('nsx_id', sa.String(length=36), nullable=False),
        sa.ForeignKeyConstraint(['neutron_id'], ['securitygroups.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('neutron_id', 'nsx_id'))
    # Execute statement to add a record in security group mappings for
    # each record in securitygroups
    op.execute("INSERT INTO neutron_nsx_security_group_mappings SELECT id,id "
               "from securitygroups")


def downgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return
    op.drop_table('neutron_nsx_security_group_mappings')
