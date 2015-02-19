# Copyright (c) 2014 OpenStack Foundation.
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

import mock

from neutron.common import test_lib
from neutron.plugins.vmware.common import sync
from neutron.tests.unit import test_extension_portsecurity as psec
from neutron.tests.unit.vmware.apiclient import fake
from neutron.tests.unit.vmware import get_fake_conf
from neutron.tests.unit.vmware import NSXAPI_NAME
from neutron.tests.unit.vmware import PLUGIN_NAME
from neutron.tests.unit.vmware import STUBS_PATH


class PortSecurityTestCase(psec.PortSecurityDBTestCase):

    def setUp(self):
        test_lib.test_config['config_files'] = [get_fake_conf('nsx.ini.test')]
        # mock api client
        self.fc = fake.FakeClient(STUBS_PATH)
        self.mock_nsx = mock.patch(NSXAPI_NAME, autospec=True)
        instance = self.mock_nsx.start()
        instance.return_value.login.return_value = "the_cookie"
        # Avoid runs of the synchronizer looping call
        patch_sync = mock.patch.object(sync, '_start_loopingcall')
        patch_sync.start()

        instance.return_value.request.side_effect = self.fc.fake_request
        super(PortSecurityTestCase, self).setUp(PLUGIN_NAME)
        self.addCleanup(self.fc.reset_all)
        self.addCleanup(self.mock_nsx.stop)
        self.addCleanup(patch_sync.stop)


class TestPortSecurity(PortSecurityTestCase, psec.TestPortSecurity):
        pass
