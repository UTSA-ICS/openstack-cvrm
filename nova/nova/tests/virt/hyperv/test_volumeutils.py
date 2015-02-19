#  Copyright 2014 Cloudbase Solutions Srl
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
from oslo.config import cfg

from nova import test
from nova.virt.hyperv import vmutils
from nova.virt.hyperv import volumeutils

CONF = cfg.CONF
CONF.import_opt('volume_attach_retry_count', 'nova.virt.hyperv.volumeops',
                'hyperv')


class VolumeUtilsTestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VolumeUtils class."""

    _FAKE_PORTAL_ADDR = '10.1.1.1'
    _FAKE_PORTAL_PORT = '3260'
    _FAKE_LUN = 0
    _FAKE_TARGET = 'iqn.2010-10.org.openstack:fake_target'

    def setUp(self):
        super(VolumeUtilsTestCase, self).setUp()
        self._volutils = volumeutils.VolumeUtils()
        self._volutils._conn_wmi = mock.MagicMock()
        self.flags(volume_attach_retry_count=4, group='hyperv')
        self.flags(volume_attach_retry_interval=0, group='hyperv')

    def _test_login_target_portal(self, portal_connected):
        fake_portal = '%s:%s' % (self._FAKE_PORTAL_ADDR,
                                 self._FAKE_PORTAL_PORT)

        self._volutils.execute = mock.MagicMock()
        if portal_connected:
            exec_output = 'Address and Socket: %s %s' % (
                self._FAKE_PORTAL_ADDR, self._FAKE_PORTAL_PORT)
        else:
            exec_output = ''

        self._volutils.execute.return_value = exec_output

        self._volutils._login_target_portal(fake_portal)

        call_list = self._volutils.execute.call_args_list
        all_call_args = [arg for call in call_list for arg in call[0]]

        if portal_connected:
            self.assertIn('RefreshTargetPortal', all_call_args)
        else:
            self.assertIn('AddTargetPortal', all_call_args)

    def test_login_connected_portal(self):
        self._test_login_target_portal(True)

    def test_login_new_portal(self):
        self._test_login_target_portal(False)

    def _test_login_target(self, target_connected, raise_exception=False):
        fake_portal = '%s:%s' % (self._FAKE_PORTAL_ADDR,
                                 self._FAKE_PORTAL_PORT)
        self._volutils.execute = mock.MagicMock()
        self._volutils._login_target_portal = mock.MagicMock()

        if target_connected:
            self._volutils.execute.return_value = self._FAKE_TARGET
        elif raise_exception:
            self._volutils.execute.return_value = ''
        else:
            self._volutils.execute.side_effect = (
                ['', '', '', self._FAKE_TARGET, ''])

        if raise_exception:
            self.assertRaises(vmutils.HyperVException,
                              self._volutils.login_storage_target,
                              self._FAKE_LUN, self._FAKE_TARGET, fake_portal)
        else:
            self._volutils.login_storage_target(self._FAKE_LUN,
                                                self._FAKE_TARGET,
                                                fake_portal)

            call_list = self._volutils.execute.call_args_list
            all_call_args = [arg for call in call_list for arg in call[0]]

            if target_connected:
                self.assertNotIn('qlogintarget', all_call_args)
            else:
                self.assertIn('qlogintarget', all_call_args)

    def test_login_connected_target(self):
        self._test_login_target(True)

    def test_login_disconncted_target(self):
        self._test_login_target(False)

    def test_login_target_exception(self):
        self._test_login_target(False, True)

    def _test_execute_wrapper(self, raise_exception):
        fake_cmd = ('iscsicli.exe', 'ListTargetPortals')

        if raise_exception:
            output = 'fake error'
        else:
            output = 'The operation completed successfully'

        with mock.patch('nova.utils.execute') as fake_execute:
            fake_execute.return_value = (output, None)

            if raise_exception:
                self.assertRaises(vmutils.HyperVException,
                                  self._volutils.execute,
                                  *fake_cmd)
            else:
                ret_val = self._volutils.execute(*fake_cmd)
                self.assertEqual(output, ret_val)

    def test_execute_raise_exception(self):
        self._test_execute_wrapper(True)

    def test_execute_exception(self):
        self._test_execute_wrapper(False)
