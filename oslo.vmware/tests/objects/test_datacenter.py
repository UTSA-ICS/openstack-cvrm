# Copyright (c) 2014 VMware, Inc.
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

import mock

from oslo.vmware.objects import datacenter
from tests import base


class DatacenterTestCase(base.TestCase):

    """Test the Datacenter object."""

    def test_dc(self):
        self.assertRaises(ValueError, datacenter.Datacenter, None, 'dc-1')
        self.assertRaises(ValueError, datacenter.Datacenter, mock.Mock(), None)
        dc = datacenter.Datacenter('ref', 'name')
        self.assertEqual('ref', dc.ref)
        self.assertEqual('name', dc.name)
