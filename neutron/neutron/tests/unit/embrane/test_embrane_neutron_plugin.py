# vim:  tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 Embrane, Inc.
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
#
# @author:  Ivar Lazzaro, Embrane, Inc.

import sys

import mock
from oslo.config import cfg

from neutron.db import api as db
from neutron.plugins.embrane.common import config  # noqa
from neutron.tests.unit import test_db_plugin as test_plugin

PLUGIN_NAME = ('neutron.plugins.embrane.plugins.embrane_fake_plugin.'
               'EmbraneFakePlugin')
sys.modules["heleosapi"] = mock.Mock()


class EmbranePluginV2TestCase(test_plugin.NeutronDbPluginV2TestCase):
    _plugin_name = PLUGIN_NAME

    def setUp(self):
        cfg.CONF.set_override('admin_password', "admin123", 'heleos')
        self.addCleanup(db.clear_db)
        super(EmbranePluginV2TestCase, self).setUp(self._plugin_name)


class TestEmbraneBasicGet(test_plugin.TestBasicGet, EmbranePluginV2TestCase):
    pass


class TestEmbraneV2HTTPResponse(test_plugin.TestV2HTTPResponse,
                                EmbranePluginV2TestCase):
    pass


class TestEmbranePortsV2(test_plugin.TestPortsV2, EmbranePluginV2TestCase):

    def test_create_ports_bulk_emulated_plugin_failure(self):
        self.skip("Temporary skipping due to incompatibility with the"
                  " plugin dynamic class type")

    def test_recycle_expired_previously_run_within_context(self):
        self.skip("Temporary skipping due to incompatibility with the"
                  " plugin dynamic class type")

    def test_recycle_held_ip_address(self):
        self.skip("Temporary skipping due to incompatibility with the"
                  " plugin dynamic class type")


class TestEmbraneNetworksV2(test_plugin.TestNetworksV2,
                            EmbranePluginV2TestCase):

    def test_create_networks_bulk_emulated_plugin_failure(self):
        self.skip("Temporary skipping due to incompatibility with the"
                  " plugin dynamic class type")


class TestEmbraneSubnetsV2(test_plugin.TestSubnetsV2,
                           EmbranePluginV2TestCase):

    def test_create_subnets_bulk_emulated_plugin_failure(self):
        self.skip("Temporary skipping due to incompatibility with the"
                  " plugin dynamic class type")
