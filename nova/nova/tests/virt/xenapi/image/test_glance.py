# Copyright 2013 OpenStack Foundation
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

import time

from nova import context
from nova import exception
from nova.tests.virt.xenapi import stubs
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi.image import glance
from nova.virt.xenapi import vm_utils


class TestGlanceStore(stubs.XenAPITestBaseNoDB):
    def setUp(self):
        super(TestGlanceStore, self).setUp()
        self.store = glance.GlanceStore()

        self.flags(glance_host='1.1.1.1',
                   glance_port=123,
                   glance_api_insecure=False)
        self.flags(connection_url='test_url',
                   connection_password='test_pass',
                   group='xenserver')

        self.context = context.RequestContext(
                'user', 'project', auth_token='foobar')

        fake.reset()
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)
        self.session = driver._session

        self.stubs.Set(
                vm_utils, 'get_sr_path', lambda *a, **kw: '/fake/sr/path')

        self.instance = {'uuid': 'blah',
                         'system_metadata': [],
                         'auto_disk_config': True,
                         'os_type': 'default',
                         'xenapi_use_agent': 'true'}

    def _get_params(self):
        return {'image_id': 'fake_image_uuid',
                'glance_host': '1.1.1.1',
                'glance_port': 123,
                'glance_use_ssl': False,
                'sr_path': '/fake/sr/path',
                'extra_headers': {'X-Service-Catalog': '[]',
                                  'X-Auth-Token': 'foobar',
                                  'X-Roles': '',
                                  'X-Tenant-Id': 'project',
                                  'X-User-Id': 'user',
                                  'X-Identity-Status': 'Confirmed'}}

    def _get_download_params(self):
        params = self._get_params()
        params['uuid_stack'] = ['uuid1']
        return params

    def test_download_image(self):
        params = self._get_download_params()

        self.stubs.Set(vm_utils, '_make_uuid_stack',
                       lambda *a, **kw: ['uuid1'])

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.session.call_plugin_serialized('glance', 'download_vhd', **params)
        self.mox.ReplayAll()

        vdis = self.store.download_image(
                self.context, self.session, self.instance, 'fake_image_uuid')

        self.mox.VerifyAll()

    def _get_upload_params(self, auto_disk_config=True,
                           expected_os_type='default'):
        params = self._get_params()
        params['vdi_uuids'] = ['fake_vdi_uuid']
        params['properties'] = {'auto_disk_config': auto_disk_config,
                                'os_type': expected_os_type}
        return params

    def _test_upload_image(self, auto_disk_config, expected_os_type='default'):
        params = self._get_upload_params(auto_disk_config, expected_os_type)

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.session.call_plugin_serialized('glance', 'upload_vhd', **params)

        self.mox.ReplayAll()
        self.store.upload_image(self.context, self.session, self.instance,
                                ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()

    def test_upload_image(self):
        self._test_upload_image(True)

    def test_upload_image_None_os_type(self):
        self.instance['os_type'] = None
        self._test_upload_image(True, 'linux')

    def test_upload_image_no_os_type(self):
        del self.instance['os_type']
        self._test_upload_image(True, 'linux')

    def test_upload_image_auto_config_disk_disabled(self):
        sys_meta = [{"key": "image_auto_disk_config", "value": "Disabled"}]
        self.instance["system_metadata"] = sys_meta
        self._test_upload_image("disabled")

    def test_upload_image_raises_exception(self):
        params = self._get_upload_params()

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(RuntimeError)
        self.mox.ReplayAll()

        self.assertRaises(RuntimeError, self.store.upload_image,
                          self.context, self.session, self.instance,
                          ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()

    def test_upload_image_retries_then_raises_exception(self):
        self.flags(glance_num_retries=2)
        params = self._get_upload_params()

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.mox.StubOutWithMock(time, 'sleep')
        error_details = ["", "", "RetryableError", ""]
        error = self.session.XenAPI.Failure(details=error_details)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        time.sleep(0.5)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        time.sleep(1)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        self.mox.ReplayAll()

        self.assertRaises(exception.CouldNotUploadImage,
                          self.store.upload_image,
                          self.context, self.session, self.instance,
                          ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()

    def test_upload_image_retries_on_signal_exception(self):
        self.flags(glance_num_retries=2)
        params = self._get_upload_params()

        self.mox.StubOutWithMock(self.session, 'call_plugin_serialized')
        self.mox.StubOutWithMock(time, 'sleep')
        error_details = ["", "task signaled", "", ""]
        error = self.session.XenAPI.Failure(details=error_details)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        time.sleep(0.5)
        # Note(johngarbutt) XenServer 6.1 and later has this error
        error_details = ["", "signal: SIGTERM", "", ""]
        error = self.session.XenAPI.Failure(details=error_details)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params).AndRaise(error)
        time.sleep(1)
        self.session.call_plugin_serialized('glance', 'upload_vhd',
                                            **params)
        self.mox.ReplayAll()

        self.store.upload_image(self.context, self.session, self.instance,
                                ['fake_vdi_uuid'], 'fake_image_uuid')
        self.mox.VerifyAll()
