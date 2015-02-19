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
from nova.virt.hyperv import volumeutilsv2

CONF = cfg.CONF
CONF.import_opt('volume_attach_retry_count', 'nova.virt.hyperv.volumeops',
                'hyperv')


class VolumeUtilsV2TestCase(test.NoDBTestCase):
    """Unit tests for the Hyper-V VolumeUtilsV2 class."""

    _FAKE_PORTAL_ADDR = '10.1.1.1'
    _FAKE_PORTAL_PORT = '3260'
    _FAKE_LUN = 0
    _FAKE_TARGET = 'iqn.2010-10.org.openstack:fake_target'

    def setUp(self):
        super(VolumeUtilsV2TestCase, self).setUp()
        self._volutilsv2 = volumeutilsv2.VolumeUtilsV2()
        self._volutilsv2._conn_storage = mock.MagicMock()
        self.flags(volume_attach_retry_count=4, group='hyperv')
        self.flags(volume_attach_retry_interval=0, group='hyperv')

    def _test_login_target_portal(self, portal_connected):
        fake_portal = '%s:%s' % (self._FAKE_PORTAL_ADDR,
                                 self._FAKE_PORTAL_PORT)
        fake_portal_object = mock.MagicMock()
        _query = self._volutilsv2._conn_storage.query
        self._volutilsv2._conn_storage.MSFT_iSCSITargetPortal = (
            fake_portal_object)

        if portal_connected:
            _query.return_value = [fake_portal_object]
        else:
            _query.return_value = None

        self._volutilsv2._login_target_portal(fake_portal)

        if portal_connected:
            fake_portal_object.Update.assert_called_once_with()
        else:
            fake_portal_object.New.assert_called_once_with(
                TargetPortalAddress=self._FAKE_PORTAL_ADDR,
                TargetPortalPortNumber=self._FAKE_PORTAL_PORT)

    def test_login_connected_portal(self):
        self._test_login_target_portal(True)

    def test_login_new_portal(self):
        self._test_login_target_portal(False)

    def _test_login_target(self, target_connected, raise_exception=False):
        fake_portal = '%s:%s' % (self._FAKE_PORTAL_ADDR,
                                 self._FAKE_PORTAL_PORT)

        fake_target_object = mock.MagicMock()

        if target_connected:
            fake_target_object.IsConnected = True
        elif not raise_exception:
            type(fake_target_object).IsConnected = mock.PropertyMock(
                side_effect=[False, True])
        else:
            fake_target_object.IsConnected = False

        _query = self._volutilsv2._conn_storage.query
        _query.return_value = [fake_target_object]

        self._volutilsv2._conn_storage.MSFT_iSCSITarget = (
            fake_target_object)

        if raise_exception:
            self.assertRaises(vmutils.HyperVException,
                              self._volutilsv2.login_storage_target,
                              self._FAKE_LUN, self._FAKE_TARGET, fake_portal)
        else:
            self._volutilsv2.login_storage_target(self._FAKE_LUN,
                                                  self._FAKE_TARGET,
                                                  fake_portal)

            if target_connected:
                fake_target_object.Update.assert_called_with()
            else:
                fake_target_object.Connect.assert_called_once_with(
                    IsPersistent=True, NodeAddress=self._FAKE_TARGET)

    def test_login_connected_target(self):
        self._test_login_target(True)

    def test_login_disconncted_target(self):
        self._test_login_target(False)

    def test_login_target_exception(self):
        self._test_login_target(False, True)
