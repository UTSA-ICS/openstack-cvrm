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

"""nsx_gw_devices

Revision ID: 19180cf98af6
Revises: 117643811bca
Create Date: 2014-02-26 02:46:26.151741

"""

# revision identifiers, used by Alembic.
revision = '19180cf98af6'
down_revision = '117643811bca'

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

    op.create_table(
        'networkgatewaydevicereferences',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('network_gateway_id', sa.String(length=36), nullable=True),
        sa.Column('interface_name', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['network_gateway_id'], ['networkgateways.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id', 'network_gateway_id', 'interface_name'),
        mysql_engine='InnoDB')
    # Copy data from networkgatewaydevices into networkgatewaydevicereference
    op.execute("INSERT INTO networkgatewaydevicereferences SELECT "
               "id, network_gateway_id, interface_name FROM "
               "networkgatewaydevices")
    # drop networkgatewaydevices
    op.drop_table('networkgatewaydevices')
    op.create_table(
        'networkgatewaydevices',
        sa.Column('tenant_id', sa.String(length=255), nullable=True),
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('nsx_id', sa.String(length=36), nullable=True),
        sa.Column('name', sa.String(length=255), nullable=True),
        sa.Column('connector_type', sa.String(length=10), nullable=True),
        sa.Column('connector_ip', sa.String(length=64), nullable=True),
        sa.Column('status', sa.String(length=16), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB')
    # Create a networkgatewaydevice for each existing reference.
    # For existing references nsx_id == neutron_id
    # Do not fill conenctor info as they would be unknown
    op.execute("INSERT INTO networkgatewaydevices (id, nsx_id, tenant_id) "
               "SELECT gw_dev_ref.id, gw_dev_ref.id as nsx_id, tenant_id "
               "FROM networkgatewaydevicereferences AS gw_dev_ref "
               "INNER JOIN networkgateways AS net_gw ON "
               "gw_dev_ref.network_gateway_id=net_gw.id")


def downgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    op.drop_table('networkgatewaydevices')
    # Re-create previous version of networkgatewaydevices table
    op.create_table(
        'networkgatewaydevices',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('network_gateway_id', sa.String(length=36), nullable=True),
        sa.Column('interface_name', sa.String(length=64), nullable=True),
        sa.ForeignKeyConstraint(['network_gateway_id'], ['networkgateways.id'],
                                ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        mysql_engine='InnoDB')
    # Copy from networkgatewaydevicereferences to networkgatewaydevices
    op.execute("INSERT INTO networkgatewaydevices SELECT "
               "id, network_gateway_id, interface_name FROM "
               "networkgatewaydevicereferences")
    # Dropt networkgatewaydevicereferences
    op.drop_table('networkgatewaydevicereferences')
