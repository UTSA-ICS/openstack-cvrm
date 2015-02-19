# vim: tabstop=4 shiftwidth=4 softtabstop=4
#
# Copyright 2014 Yahoo! Inc.
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

"""icehouse

Revision ID: icehouse
Revises: 5ac1c354a051
Create Date: 2013-03-28 00:00:00.000000

"""

# revision identifiers, used by Alembic.
revision = 'icehouse'
down_revision = '5ac1c354a051'

# Change to ['*'] if this migration applies to all plugins

migration_for_plugins = ['*']


def upgrade(active_plugins=None, options=None):
    """A no-op migration for marking the Icehouse release."""
    pass


def downgrade(active_plugins=None, options=None):
    """A no-op migration for marking the Icehouse release."""
    pass
