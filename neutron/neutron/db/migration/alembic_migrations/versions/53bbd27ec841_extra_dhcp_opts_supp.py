# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2013 OpenStack Foundation
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

"""Extra dhcp opts support

Revision ID: 53bbd27ec841
Revises: 40dffbf4b549
Create Date: 2013-05-09 15:36:50.485036

"""

# revision identifiers, used by Alembic.
revision = '53bbd27ec841'
down_revision = '40dffbf4b549'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = [
    'neutron.plugins.openvswitch.ovs_neutron_plugin.OVSNeutronPluginV2',
    'neutron.plugins.ml2.plugin.Ml2Plugin',
    'neutron.plugins.bigswitch.plugin.NeutronRestProxyV2'
]

from alembic import op
import sqlalchemy as sa


from neutron.db import migration


def upgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    op.create_table(
        'extradhcpopts',
        sa.Column('id', sa.String(length=36), nullable=False),
        sa.Column('port_id', sa.String(length=36), nullable=False),
        sa.Column('opt_name', sa.String(length=64), nullable=False),
        sa.Column('opt_value', sa.String(length=255), nullable=False),
        sa.ForeignKeyConstraint(['port_id'], ['ports.id'], ondelete='CASCADE'),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('port_id', 'opt_name', name='uidx_portid_optname'))


def downgrade(active_plugins=None, options=None):
    if not migration.should_run(active_plugins, migration_for_plugins):
        return

    ### commands auto generated by Alembic - please adjust! ###
    op.drop_table('extradhcpopts')
    ### end Alembic commands ###
