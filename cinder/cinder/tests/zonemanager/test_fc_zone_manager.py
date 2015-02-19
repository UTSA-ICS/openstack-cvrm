#    (c) Copyright 2014 Brocade Communications Systems Inc.
#    All Rights Reserved.
#
#    Copyright 2014 OpenStack Foundation
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


"""Unit tests for FC Zone Manager."""

import mock

from cinder import exception
from cinder import test
from cinder.volume import configuration as conf
from cinder.zonemanager.drivers.fc_zone_driver import FCZoneDriver
from cinder.zonemanager.fc_zone_manager import ZoneManager
from mock import Mock

fabric_name = 'BRCD_FAB_3'
init_target_map = {'10008c7cff523b01': ['20240002ac000a50']}
fabric_map = {'BRCD_FAB_3': ['20240002ac000a50']}
target_list = ['20240002ac000a50']


class TestFCZoneManager(ZoneManager, test.TestCase):

    def setUp(self):
        super(TestFCZoneManager, self).setUp()
        self.configuration = conf.Configuration(None)
        self.configuration.set_default('fc_fabric_names', fabric_name)
        self.driver = Mock(FCZoneDriver)

    def __init__(self, *args, **kwargs):
        test.TestCase.__init__(self, *args, **kwargs)

    def test_add_connection(self):
        with mock.patch.object(self.driver, 'add_connection')\
                as add_connection_mock:
            self.driver.get_san_context.return_value = fabric_map
            self.add_connection(init_target_map)
            self.driver.get_san_context.assert_called_once(target_list)
            add_connection_mock.assert_called_once_with(fabric_name,
                                                        init_target_map)

    def test_add_connection_error(self):
        with mock.patch.object(self.driver, 'add_connection')\
                as add_connection_mock:
            add_connection_mock.side_effect = exception.FCZoneDriverException
            self.assertRaises(exception.ZoneManagerException,
                              self.add_connection, init_target_map)

    def test_delete_connection(self):
        with mock.patch.object(self.driver, 'delete_connection')\
                as delete_connection_mock:
            self.driver.get_san_context.return_value = fabric_map
            self.delete_connection(init_target_map)
            self.driver.get_san_context.assert_called_once_with(target_list)
            delete_connection_mock.assert_called_once_with(fabric_name,
                                                           init_target_map)

    def test_delete_connection_error(self):
        with mock.patch.object(self.driver, 'delete_connection')\
                as del_connection_mock:
            del_connection_mock.side_effect = exception.FCZoneDriverException
            self.assertRaises(exception.ZoneManagerException,
                              self.delete_connection, init_target_map)
