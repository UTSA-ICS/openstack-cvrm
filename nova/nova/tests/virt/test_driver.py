# Copyright (c) 2013 Citrix Systems, Inc.
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

from nova import test
from nova.virt import driver


class FakeDriver(object):
    def __init__(self, *args, **kwargs):
        self.args = args
        self.kwargs = kwargs


class FakeDriver2(FakeDriver):
    pass


class ToDriverRegistryTestCase(test.NoDBTestCase):

    def assertDriverInstance(self, inst, class_, *args, **kwargs):
        self.assertEqual(class_, inst.__class__)
        self.assertEqual(args, inst.args)
        self.assertEqual(kwargs, inst.kwargs)

    def test_driver_dict_from_config(self):
        drvs = driver.driver_dict_from_config(
            [
                'key1=nova.tests.virt.test_driver.FakeDriver',
                'key2=nova.tests.virt.test_driver.FakeDriver2',
            ], 'arg1', 'arg2', param1='value1', param2='value2'
        )

        self.assertEqual(
            sorted(['key1', 'key2']),
            sorted(drvs.keys())
        )

        self.assertDriverInstance(
            drvs['key1'],
            FakeDriver, 'arg1', 'arg2', param1='value1',
            param2='value2')

        self.assertDriverInstance(
            drvs['key2'],
            FakeDriver2, 'arg1', 'arg2', param1='value1',
            param2='value2')
