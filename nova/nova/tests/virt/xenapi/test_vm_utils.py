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

import contextlib
import uuid

from eventlet import greenthread
import fixtures
import mock
import mox
from oslo.config import cfg

from nova.compute import flavors
from nova.compute import power_state
from nova.compute import vm_mode
from nova import context
from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import processutils
from nova.openstack.common import timeutils
from nova.openstack.common import units
from nova.openstack.common import uuidutils
from nova import test
from nova.tests import fake_instance
from nova.tests.virt.xenapi import stubs
from nova.tests.virt.xenapi import test_xenapi
from nova import utils
from nova.virt.xenapi.client import session as xenapi_session
from nova.virt.xenapi import driver as xenapi_conn
from nova.virt.xenapi import fake
from nova.virt.xenapi import vm_utils
from nova.virt.xenapi import volume_utils

CONF = cfg.CONF
XENSM_TYPE = 'xensm'
ISCSI_TYPE = 'iscsi'


def get_fake_connection_data(sr_type):
    fakes = {XENSM_TYPE: {'sr_uuid': 'falseSR',
                          'name_label': 'fake_storage',
                          'name_description': 'test purposes',
                          'server': 'myserver',
                          'serverpath': '/local/scratch/myname',
                          'sr_type': 'nfs',
                          'introduce_sr_keys': ['server',
                                                'serverpath',
                                                'sr_type'],
                          'vdi_uuid': 'falseVDI'},
             ISCSI_TYPE: {'volume_id': 'fake_volume_id',
                          'target_lun': 1,
                          'target_iqn': 'fake_iqn:volume-fake_volume_id',
                          'target_portal': u'localhost:3260',
                          'target_discovered': False}, }
    return fakes[sr_type]


def _get_fake_session(error=None):
    session = mock.Mock()
    xenapi_session.apply_session_helpers(session)

    if error is not None:
        class FakeException(Exception):
            details = [error, "a", "b", "c"]

        session.XenAPI.Failure = FakeException
        session.call_xenapi.side_effect = FakeException

    return session


@contextlib.contextmanager
def contextified(result):
    yield result


def _fake_noop(*args, **kwargs):
    return


class VMUtilsTestBase(stubs.XenAPITestBaseNoDB):
    pass


class LookupTestCase(VMUtilsTestBase):
    def setUp(self):
        super(LookupTestCase, self).setUp()
        self.session = self.mox.CreateMockAnything('Fake Session')
        self.name_label = 'my_vm'

    def _do_mock(self, result):
        self.session.call_xenapi(
            "VM.get_by_name_label", self.name_label).AndReturn(result)
        self.mox.ReplayAll()

    def test_normal(self):
        self._do_mock(['x'])
        result = vm_utils.lookup(self.session, self.name_label)
        self.assertEqual('x', result)

    def test_no_result(self):
        self._do_mock([])
        result = vm_utils.lookup(self.session, self.name_label)
        self.assertIsNone(result)

    def test_too_many(self):
        self._do_mock(['a', 'b'])
        self.assertRaises(exception.InstanceExists,
                          vm_utils.lookup,
                          self.session, self.name_label)

    def test_rescue_none(self):
        self.session.call_xenapi(
            "VM.get_by_name_label", self.name_label + '-rescue').AndReturn([])
        self._do_mock(['x'])
        result = vm_utils.lookup(self.session, self.name_label,
                                 check_rescue=True)
        self.assertEqual('x', result)

    def test_rescue_found(self):
        self.session.call_xenapi(
            "VM.get_by_name_label",
            self.name_label + '-rescue').AndReturn(['y'])
        self.mox.ReplayAll()
        result = vm_utils.lookup(self.session, self.name_label,
                                 check_rescue=True)
        self.assertEqual('y', result)

    def test_rescue_too_many(self):
        self.session.call_xenapi(
            "VM.get_by_name_label",
            self.name_label + '-rescue').AndReturn(['a', 'b', 'c'])
        self.mox.ReplayAll()
        self.assertRaises(exception.InstanceExists,
                          vm_utils.lookup,
                          self.session, self.name_label,
                          check_rescue=True)


class GenerateConfigDriveTestCase(VMUtilsTestBase):
    def test_no_admin_pass(self):
        instance = {}

        self.mox.StubOutWithMock(vm_utils, 'safe_find_sr')
        vm_utils.safe_find_sr('session').AndReturn('sr_ref')

        self.mox.StubOutWithMock(vm_utils, 'create_vdi')
        vm_utils.create_vdi('session', 'sr_ref', instance, 'config-2',
                            'configdrive',
                            64 * units.Mi).AndReturn('vdi_ref')

        self.mox.StubOutWithMock(vm_utils, 'vdi_attached_here')
        vm_utils.vdi_attached_here(
            'session', 'vdi_ref', read_only=False).AndReturn(
                contextified('mounted_dev'))

        class FakeInstanceMetadata(object):
            def __init__(_self, instance, content=None, extra_md=None,
                         network_info=None):
                self.assertEqual(network_info, "nw_info")

            def metadata_for_config_drive(_self):
                return []

        self.useFixture(fixtures.MonkeyPatch(
                'nova.api.metadata.base.InstanceMetadata',
                FakeInstanceMetadata))

        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('genisoimage', '-o', mox.IgnoreArg(), '-ldots',
                      '-allow-lowercase', '-allow-multidot', '-l',
                      '-publisher', mox.IgnoreArg(), '-quiet',
                      '-J', '-r', '-V', 'config-2', mox.IgnoreArg(),
                      attempts=1, run_as_root=False).AndReturn(None)
        utils.execute('dd', mox.IgnoreArg(), mox.IgnoreArg(),
                      mox.IgnoreArg(), run_as_root=True).AndReturn(None)

        self.mox.StubOutWithMock(vm_utils, 'create_vbd')
        vm_utils.create_vbd('session', 'vm_ref', 'vdi_ref', mox.IgnoreArg(),
                            bootable=False, read_only=True).AndReturn(None)

        self.mox.ReplayAll()

        # And the actual call we're testing
        vm_utils.generate_configdrive('session', instance, 'vm_ref',
                                      'userdevice', "nw_info")

    @mock.patch.object(vm_utils, "destroy_vdi")
    @mock.patch.object(vm_utils, "vdi_attached_here")
    @mock.patch.object(vm_utils, "create_vdi")
    @mock.patch.object(vm_utils, "safe_find_sr")
    def test_vdi_cleaned_up(self, mock_find, mock_create_vdi, mock_attached,
                            mock_destroy):
        mock_create_vdi.return_value = 'vdi_ref'
        mock_attached.side_effect = test.TestingException
        mock_destroy.side_effect = volume_utils.StorageError

        instance = {"uuid": "asdf"}
        self.assertRaises(test.TestingException,
                          vm_utils.generate_configdrive,
                          'session', instance, 'vm_ref', 'userdevice',
                          'nw_info')
        mock_destroy.assert_called_once_with('session', 'vdi_ref')


class XenAPIGetUUID(VMUtilsTestBase):
    def test_get_this_vm_uuid_new_kernel(self):
        self.mox.StubOutWithMock(vm_utils, '_get_sys_hypervisor_uuid')

        vm_utils._get_sys_hypervisor_uuid().AndReturn(
            '2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f')

        self.mox.ReplayAll()
        self.assertEqual('2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f',
                         vm_utils.get_this_vm_uuid(None))
        self.mox.VerifyAll()

    def test_get_this_vm_uuid_old_kernel_reboot(self):
        self.mox.StubOutWithMock(vm_utils, '_get_sys_hypervisor_uuid')
        self.mox.StubOutWithMock(utils, 'execute')

        vm_utils._get_sys_hypervisor_uuid().AndRaise(
            IOError(13, 'Permission denied'))
        utils.execute('xenstore-read', 'domid', run_as_root=True).AndReturn(
            ('27', ''))
        utils.execute('xenstore-read', '/local/domain/27/vm',
                      run_as_root=True).AndReturn(
            ('/vm/2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f', ''))

        self.mox.ReplayAll()
        self.assertEqual('2f46f0f5-f14c-ef1b-1fac-9eeca0888a3f',
                         vm_utils.get_this_vm_uuid(None))
        self.mox.VerifyAll()


class FakeSession(object):
    def call_xenapi(self, *args):
        pass

    def call_plugin(self, *args):
        pass

    def call_plugin_serialized(self, plugin, fn, *args, **kwargs):
        pass

    def call_plugin_serialized_with_retry(self, plugin, fn, num_retries,
                                          callback, *args, **kwargs):
        pass


class FetchVhdImageTestCase(VMUtilsTestBase):
    def setUp(self):
        super(FetchVhdImageTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.context.auth_token = 'auth_token'
        self.session = FakeSession()
        self.instance = {"uuid": "uuid"}

        self.mox.StubOutWithMock(vm_utils, '_make_uuid_stack')
        vm_utils._make_uuid_stack().AndReturn(["uuid_stack"])

        self.mox.StubOutWithMock(vm_utils, 'get_sr_path')
        vm_utils.get_sr_path(self.session).AndReturn('sr_path')

    def _stub_glance_download_vhd(self, raise_exc=None):
        self.mox.StubOutWithMock(
                self.session, 'call_plugin_serialized_with_retry')
        func = self.session.call_plugin_serialized_with_retry(
                'glance', 'download_vhd', 0, mox.IgnoreArg(),
                extra_headers={'X-Service-Catalog': '[]',
                               'X-Auth-Token': 'auth_token',
                               'X-Roles': '',
                               'X-Tenant-Id': None,
                               'X-User-Id': None,
                               'X-Identity-Status': 'Confirmed'},
                image_id='image_id',
                uuid_stack=["uuid_stack"],
                sr_path='sr_path')

        if raise_exc:
            func.AndRaise(raise_exc)
        else:
            func.AndReturn({'root': {'uuid': 'vdi'}})

    def _stub_bittorrent_download_vhd(self, raise_exc=None):
        self.mox.StubOutWithMock(
                self.session, 'call_plugin_serialized')
        func = self.session.call_plugin_serialized(
            'bittorrent', 'download_vhd',
            image_id='image_id',
            uuid_stack=["uuid_stack"],
            sr_path='sr_path',
            torrent_download_stall_cutoff=600,
            torrent_listen_port_start=6881,
            torrent_listen_port_end=6891,
            torrent_max_last_accessed=86400,
            torrent_max_seeder_processes_per_host=1,
            torrent_seed_chance=1.0,
            torrent_seed_duration=3600,
            torrent_url='http://foo/image_id.torrent'
        )
        if raise_exc:
            func.AndRaise(raise_exc)
        else:
            func.AndReturn({'root': {'uuid': 'vdi'}})

    def test_fetch_vhd_image_works_with_glance(self):
        self.mox.StubOutWithMock(vm_utils, '_image_uses_bittorrent')
        vm_utils._image_uses_bittorrent(
            self.context, self.instance).AndReturn(False)

        self._stub_glance_download_vhd()

        self.mox.StubOutWithMock(vm_utils, 'safe_find_sr')
        vm_utils.safe_find_sr(self.session).AndReturn("sr")

        self.mox.StubOutWithMock(vm_utils, '_scan_sr')
        vm_utils._scan_sr(self.session, "sr")

        self.mox.StubOutWithMock(vm_utils, '_check_vdi_size')
        vm_utils._check_vdi_size(
                self.context, self.session, self.instance, "vdi")

        self.mox.ReplayAll()

        self.assertEqual("vdi", vm_utils._fetch_vhd_image(self.context,
            self.session, self.instance, 'image_id')['root']['uuid'])

        self.mox.VerifyAll()

    def test_fetch_vhd_image_works_with_bittorrent(self):
        cfg.CONF.import_opt('torrent_base_url',
                            'nova.virt.xenapi.image.bittorrent',
                            group='xenserver')
        self.flags(torrent_base_url='http://foo', group='xenserver')

        self.mox.StubOutWithMock(vm_utils, '_image_uses_bittorrent')
        vm_utils._image_uses_bittorrent(
            self.context, self.instance).AndReturn(True)

        self._stub_bittorrent_download_vhd()

        self.mox.StubOutWithMock(vm_utils, 'safe_find_sr')
        vm_utils.safe_find_sr(self.session).AndReturn("sr")

        self.mox.StubOutWithMock(vm_utils, '_scan_sr')
        vm_utils._scan_sr(self.session, "sr")

        self.mox.StubOutWithMock(vm_utils, '_check_vdi_size')
        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                                 "vdi")

        self.mox.ReplayAll()

        self.assertEqual("vdi", vm_utils._fetch_vhd_image(self.context,
            self.session, self.instance, 'image_id')['root']['uuid'])

        self.mox.VerifyAll()

    def test_fetch_vhd_image_cleans_up_vdi_on_fail(self):
        self.mox.StubOutWithMock(vm_utils, '_image_uses_bittorrent')
        vm_utils._image_uses_bittorrent(
            self.context, self.instance).AndReturn(False)

        self._stub_glance_download_vhd()

        self.mox.StubOutWithMock(vm_utils, 'safe_find_sr')
        vm_utils.safe_find_sr(self.session).AndReturn("sr")

        self.mox.StubOutWithMock(vm_utils, '_scan_sr')
        vm_utils._scan_sr(self.session, "sr")

        self.mox.StubOutWithMock(vm_utils, '_check_vdi_size')
        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                "vdi").AndRaise(exception.FlavorDiskTooSmall)

        self.mox.StubOutWithMock(self.session, 'call_xenapi')
        self.session.call_xenapi("VDI.get_by_uuid", "vdi").AndReturn("ref")

        self.mox.StubOutWithMock(vm_utils, 'destroy_vdi')
        vm_utils.destroy_vdi(self.session,
                             "ref").AndRaise(volume_utils.StorageError)

        self.mox.ReplayAll()

        self.assertRaises(exception.FlavorDiskTooSmall,
                vm_utils._fetch_vhd_image, self.context, self.session,
                self.instance, 'image_id')

        self.mox.VerifyAll()

    def test_fallback_to_default_handler(self):
        cfg.CONF.import_opt('torrent_base_url',
                            'nova.virt.xenapi.image.bittorrent',
                            group='xenserver')
        self.flags(torrent_base_url='http://foo', group='xenserver')

        self.mox.StubOutWithMock(vm_utils, '_image_uses_bittorrent')
        vm_utils._image_uses_bittorrent(
            self.context, self.instance).AndReturn(True)

        self._stub_bittorrent_download_vhd(raise_exc=RuntimeError)

        vm_utils._make_uuid_stack().AndReturn(["uuid_stack"])
        vm_utils.get_sr_path(self.session).AndReturn('sr_path')

        self._stub_glance_download_vhd()

        self.mox.StubOutWithMock(vm_utils, 'safe_find_sr')
        vm_utils.safe_find_sr(self.session).AndReturn("sr")

        self.mox.StubOutWithMock(vm_utils, '_scan_sr')
        vm_utils._scan_sr(self.session, "sr")

        self.mox.StubOutWithMock(vm_utils, '_check_vdi_size')
        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                                 "vdi")

        self.mox.ReplayAll()

        self.assertEqual("vdi", vm_utils._fetch_vhd_image(self.context,
            self.session, self.instance, 'image_id')['root']['uuid'])

        self.mox.VerifyAll()

    def test_default_handler_doesnt_fallback_to_itself(self):
        cfg.CONF.import_opt('torrent_base_url',
                            'nova.virt.xenapi.image.bittorrent',
                            group='xenserver')
        self.flags(torrent_base_url='http://foo', group='xenserver')

        self.mox.StubOutWithMock(vm_utils, '_image_uses_bittorrent')
        vm_utils._image_uses_bittorrent(
            self.context, self.instance).AndReturn(False)

        self._stub_glance_download_vhd(raise_exc=RuntimeError)

        self.mox.ReplayAll()

        self.assertRaises(RuntimeError, vm_utils._fetch_vhd_image,
                self.context, self.session, self.instance, 'image_id')

        self.mox.VerifyAll()


class TestImageCompression(VMUtilsTestBase):
    def test_image_compression(self):
        # Testing for nova.conf, too low, negative, and a correct value.
        self.assertIsNone(vm_utils.get_compression_level())
        self.flags(image_compression_level=0, group='xenserver')
        self.assertIsNone(vm_utils.get_compression_level())
        self.flags(image_compression_level=-6, group='xenserver')
        self.assertIsNone(vm_utils.get_compression_level())
        self.flags(image_compression_level=6, group='xenserver')
        self.assertEqual(vm_utils.get_compression_level(), 6)


class ResizeHelpersTestCase(VMUtilsTestBase):
    def test_repair_filesystem(self):
        self.mox.StubOutWithMock(utils, 'execute')

        utils.execute('e2fsck', '-f', "-y", "fakepath",
            run_as_root=True, check_exit_code=[0, 1, 2]).AndReturn(
                ("size is: 42", ""))

        self.mox.ReplayAll()

        vm_utils._repair_filesystem("fakepath")

    def _call_tune2fs_remove_journal(self, path):
        utils.execute("tune2fs", "-O ^has_journal", path, run_as_root=True)

    def _call_tune2fs_add_journal(self, path):
        utils.execute("tune2fs", "-j", path, run_as_root=True)

    def _call_parted(self, path, start, end):
        utils.execute('parted', '--script', path, 'rm', '1',
            run_as_root=True)
        utils.execute('parted', '--script', path, 'mkpart',
            'primary', '%ds' % start, '%ds' % end, run_as_root=True)

    def test_resize_part_and_fs_down_succeeds(self):
        self.mox.StubOutWithMock(vm_utils, "_repair_filesystem")
        self.mox.StubOutWithMock(utils, 'execute')

        dev_path = "/dev/fake"
        partition_path = "%s1" % dev_path
        vm_utils._repair_filesystem(partition_path)
        self._call_tune2fs_remove_journal(partition_path)
        utils.execute("resize2fs", partition_path, "10s", run_as_root=True)
        self._call_parted(dev_path, 0, 9)
        self._call_tune2fs_add_journal(partition_path)

        self.mox.ReplayAll()

        vm_utils._resize_part_and_fs("fake", 0, 20, 10)

    def test_log_progress_if_required(self):
        self.mox.StubOutWithMock(vm_utils.LOG, "debug")
        vm_utils.LOG.debug(_("Sparse copy in progress, "
                             "%(complete_pct).2f%% complete. "
                             "%(left)s bytes left to copy"),
                           {"complete_pct": 50.0, "left": 1})
        current = timeutils.utcnow()
        timeutils.set_time_override(current)
        timeutils.advance_time_seconds(vm_utils.PROGRESS_INTERVAL_SECONDS + 1)
        self.mox.ReplayAll()
        vm_utils._log_progress_if_required(1, current, 2)

    def test_log_progress_if_not_required(self):
        self.mox.StubOutWithMock(vm_utils.LOG, "debug")
        current = timeutils.utcnow()
        timeutils.set_time_override(current)
        timeutils.advance_time_seconds(vm_utils.PROGRESS_INTERVAL_SECONDS - 1)
        self.mox.ReplayAll()
        vm_utils._log_progress_if_required(1, current, 2)

    def test_resize_part_and_fs_down_fails_disk_too_big(self):
        self.mox.StubOutWithMock(vm_utils, "_repair_filesystem")
        self.mox.StubOutWithMock(utils, 'execute')

        dev_path = "/dev/fake"
        partition_path = "%s1" % dev_path
        new_sectors = 10
        vm_utils._repair_filesystem(partition_path)
        self._call_tune2fs_remove_journal(partition_path)
        mobj = utils.execute("resize2fs",
                             partition_path,
                             "%ss" % new_sectors,
                             run_as_root=True)
        mobj.AndRaise(processutils.ProcessExecutionError)
        self.mox.ReplayAll()
        self.assertRaises(exception.ResizeError,
                          vm_utils._resize_part_and_fs, "fake", 0, 20, 10)

    def test_resize_part_and_fs_up_succeeds(self):
        self.mox.StubOutWithMock(vm_utils, "_repair_filesystem")
        self.mox.StubOutWithMock(utils, 'execute')

        dev_path = "/dev/fake"
        partition_path = "%s1" % dev_path
        vm_utils._repair_filesystem(partition_path)
        self._call_tune2fs_remove_journal(partition_path)
        self._call_parted(dev_path, 0, 29)
        utils.execute("resize2fs", partition_path, run_as_root=True)
        self._call_tune2fs_add_journal(partition_path)

        self.mox.ReplayAll()

        vm_utils._resize_part_and_fs("fake", 0, 20, 30)

    def test_resize_disk_throws_on_zero_size(self):
        self.assertRaises(exception.ResizeError,
                vm_utils.resize_disk, "session", "instance", "vdi_ref",
                {"root_gb": 0})

    def test_auto_config_disk_returns_early_on_zero_size(self):
        vm_utils.try_auto_configure_disk("bad_session", "bad_vdi_ref", 0)


class CheckVDISizeTestCase(VMUtilsTestBase):
    def setUp(self):
        super(CheckVDISizeTestCase, self).setUp()
        self.context = 'fakecontext'
        self.session = 'fakesession'
        self.instance = dict(uuid='fakeinstance')
        self.vdi_uuid = 'fakeuuid'

    def test_not_too_large(self):
        self.mox.StubOutWithMock(flavors, 'extract_flavor')
        flavors.extract_flavor(self.instance).AndReturn(
                dict(root_gb=1))

        self.mox.StubOutWithMock(vm_utils, '_get_vdi_chain_size')
        vm_utils._get_vdi_chain_size(self.session,
                self.vdi_uuid).AndReturn(1073741824)

        self.mox.ReplayAll()

        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                self.vdi_uuid)

    def test_too_large(self):
        self.mox.StubOutWithMock(flavors, 'extract_flavor')
        flavors.extract_flavor(self.instance).AndReturn(
                dict(root_gb=1))

        self.mox.StubOutWithMock(vm_utils, '_get_vdi_chain_size')
        vm_utils._get_vdi_chain_size(self.session,
                self.vdi_uuid).AndReturn(11811160065)  # 10GB overhead allowed

        self.mox.ReplayAll()

        self.assertRaises(exception.FlavorDiskTooSmall,
                vm_utils._check_vdi_size, self.context, self.session,
                self.instance, self.vdi_uuid)

    def test_zero_root_gb_disables_check(self):
        self.mox.StubOutWithMock(flavors, 'extract_flavor')
        flavors.extract_flavor(self.instance).AndReturn(
                dict(root_gb=0))

        self.mox.ReplayAll()

        vm_utils._check_vdi_size(self.context, self.session, self.instance,
                self.vdi_uuid)


class GetVdisForInstanceTestCase(VMUtilsTestBase):
    """Tests get_vdis_for_instance utility method."""
    def setUp(self):
        super(GetVdisForInstanceTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.context.auth_token = 'auth_token'
        self.session = FakeSession()
        self.instance = fake_instance.fake_instance_obj(self.context)
        self.name_label = 'name'
        self.image = 'fake_image_id'

    @mock.patch.object(vm_utils, 'get_vdi_uuid_for_volume',
                       return_value=uuidutils.generate_uuid())
    def test_vdis_for_instance_bdi_password_scrubbed(self, get_uuid_mock):
        # setup fake data
        data = {'name_label': self.name_label,
                'sr_uuid': 'fake',
                'auth_password': 'scrubme'}
        bdm = [{'mount_device': '/dev/vda',
                'connection_info': {'data': data}}]
        bdi = {'root_device_name': 'vda',
               'block_device_mapping': bdm}

        # Tests that the parameters to the to_xml method are sanitized for
        # passwords when logged.
        def fake_debug(*args, **kwargs):
            if 'auth_password' in args[0]:
                self.assertNotIn('scrubme', args[0])

        with mock.patch.object(vm_utils.LOG, 'debug',
                               side_effect=fake_debug) as debug_mock:
            vdis = vm_utils.get_vdis_for_instance(self.context, self.session,
                                                  self.instance,
                                                  self.name_label, self.image,
                                                  image_type=4,
                                                  block_device_info=bdi)
            self.assertEqual(1, len(vdis))
            get_uuid_mock.assert_called_once_with(self.session, data)
            # we don't care what the log message is, we just want to make sure
            # our stub method is called which asserts the password is scrubbed
            self.assertTrue(debug_mock.called)


class GetInstanceForVdisForSrTestCase(VMUtilsTestBase):
    def setUp(self):
        super(GetInstanceForVdisForSrTestCase, self).setUp()
        self.flags(disable_process_locking=True,
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        self.flags(connection_url='test_url',
                   connection_password='test_pass',
                   group='xenserver')

    def test_get_instance_vdis_for_sr(self):
        vm_ref = fake.create_vm("foo", "Running")
        sr_ref = fake.create_sr()

        vdi_1 = fake.create_vdi('vdiname1', sr_ref)
        vdi_2 = fake.create_vdi('vdiname2', sr_ref)

        for vdi_ref in [vdi_1, vdi_2]:
            fake.create_vbd(vm_ref, vdi_ref)

        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = list(vm_utils.get_instance_vdis_for_sr(
            driver._session, vm_ref, sr_ref))

        self.assertEqual([vdi_1, vdi_2], result)

    def test_get_instance_vdis_for_sr_no_vbd(self):
        vm_ref = fake.create_vm("foo", "Running")
        sr_ref = fake.create_sr()

        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = list(vm_utils.get_instance_vdis_for_sr(
            driver._session, vm_ref, sr_ref))

        self.assertEqual([], result)

    def test_get_vdi_uuid_for_volume_with_sr_uuid(self):
        connection_data = get_fake_connection_data(XENSM_TYPE)
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        vdi_uuid = vm_utils.get_vdi_uuid_for_volume(
                driver._session, connection_data)
        self.assertEqual(vdi_uuid, 'falseVDI')

    def test_get_vdi_uuid_for_volume_failure(self):
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        def bad_introduce_sr(session, sr_uuid, label, sr_params):
            return None

        self.stubs.Set(volume_utils, 'introduce_sr', bad_introduce_sr)
        connection_data = get_fake_connection_data(XENSM_TYPE)
        self.assertRaises(exception.NovaException,
                          vm_utils.get_vdi_uuid_for_volume,
                          driver._session, connection_data)

    def test_get_vdi_uuid_for_volume_from_iscsi_vol_missing_sr_uuid(self):
        connection_data = get_fake_connection_data(ISCSI_TYPE)
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        vdi_uuid = vm_utils.get_vdi_uuid_for_volume(
                driver._session, connection_data)
        self.assertIsNotNone(vdi_uuid)


class VMRefOrRaiseVMFoundTestCase(VMUtilsTestBase):

    def test_lookup_call(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn('ignored')

        mock.ReplayAll()
        vm_utils.vm_ref_or_raise('session', 'somename')
        mock.VerifyAll()

    def test_return_value(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup(mox.IgnoreArg(), mox.IgnoreArg()).AndReturn('vmref')

        mock.ReplayAll()
        self.assertEqual(
            'vmref', vm_utils.vm_ref_or_raise('session', 'somename'))
        mock.VerifyAll()


class VMRefOrRaiseVMNotFoundTestCase(VMUtilsTestBase):

    def test_exception_raised(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn(None)

        mock.ReplayAll()
        self.assertRaises(
            exception.InstanceNotFound,
            lambda: vm_utils.vm_ref_or_raise('session', 'somename')
        )
        mock.VerifyAll()

    def test_exception_msg_contains_vm_name(self):
        mock = mox.Mox()
        mock.StubOutWithMock(vm_utils, 'lookup')

        vm_utils.lookup('session', 'somename').AndReturn(None)

        mock.ReplayAll()
        try:
            vm_utils.vm_ref_or_raise('session', 'somename')
        except exception.InstanceNotFound as e:
            self.assertTrue(
                'somename' in str(e))
        mock.VerifyAll()


class BittorrentTestCase(VMUtilsTestBase):
    def setUp(self):
        super(BittorrentTestCase, self).setUp()
        self.context = context.get_admin_context()

    def test_image_uses_bittorrent(self):
        instance = {'system_metadata': {'image_bittorrent': True}}
        self.flags(torrent_images='some', group='xenserver')
        self.assertTrue(vm_utils._image_uses_bittorrent(self.context,
                                                        instance))

    def _test_create_image(self, cache_type):
        instance = {'system_metadata': {'image_cache_in_nova': True}}
        self.flags(cache_images=cache_type, group='xenserver')

        was = {'called': None}

        def fake_create_cached_image(*args):
            was['called'] = 'some'
            return {}
        self.stubs.Set(vm_utils, '_create_cached_image',
                       fake_create_cached_image)

        def fake_fetch_image(*args):
            was['called'] = 'none'
            return {}
        self.stubs.Set(vm_utils, '_fetch_image',
                       fake_fetch_image)

        vm_utils._create_image(self.context, None, instance,
                               'foo', 'bar', 'baz')

        self.assertEqual(was['called'], cache_type)

    def test_create_image_cached(self):
        self._test_create_image('some')

    def test_create_image_uncached(self):
        self._test_create_image('none')


class ShutdownTestCase(VMUtilsTestBase):

    def test_hardshutdown_should_return_true_when_vm_is_shutdown(self):
        self.mock = mox.Mox()
        session = FakeSession()
        instance = "instance"
        vm_ref = "vm-ref"
        self.mock.StubOutWithMock(vm_utils, 'is_vm_shutdown')
        vm_utils.is_vm_shutdown(session, vm_ref).AndReturn(True)
        self.mock.StubOutWithMock(vm_utils, 'LOG')
        self.assertTrue(vm_utils.hard_shutdown_vm(
            session, instance, vm_ref))

    def test_cleanshutdown_should_return_true_when_vm_is_shutdown(self):
        self.mock = mox.Mox()
        session = FakeSession()
        instance = "instance"
        vm_ref = "vm-ref"
        self.mock.StubOutWithMock(vm_utils, 'is_vm_shutdown')
        vm_utils.is_vm_shutdown(session, vm_ref).AndReturn(True)
        self.mock.StubOutWithMock(vm_utils, 'LOG')
        self.assertTrue(vm_utils.clean_shutdown_vm(
            session, instance, vm_ref))


class CreateVBDTestCase(VMUtilsTestBase):
    def setUp(self):
        super(CreateVBDTestCase, self).setUp()
        self.session = FakeSession()
        self.mock = mox.Mox()
        self.mock.StubOutWithMock(self.session, 'call_xenapi')
        self.vbd_rec = self._generate_vbd_rec()

    def _generate_vbd_rec(self):
        vbd_rec = {}
        vbd_rec['VM'] = 'vm_ref'
        vbd_rec['VDI'] = 'vdi_ref'
        vbd_rec['userdevice'] = '0'
        vbd_rec['bootable'] = False
        vbd_rec['mode'] = 'RW'
        vbd_rec['type'] = 'disk'
        vbd_rec['unpluggable'] = True
        vbd_rec['empty'] = False
        vbd_rec['other_config'] = {}
        vbd_rec['qos_algorithm_type'] = ''
        vbd_rec['qos_algorithm_params'] = {}
        vbd_rec['qos_supported_algorithms'] = []
        return vbd_rec

    def test_create_vbd_default_args(self):
        self.session.call_xenapi('VBD.create',
                self.vbd_rec).AndReturn("vbd_ref")
        self.mock.ReplayAll()

        result = vm_utils.create_vbd(self.session, "vm_ref", "vdi_ref", 0)
        self.assertEqual(result, "vbd_ref")
        self.mock.VerifyAll()

    def test_create_vbd_osvol(self):
        self.session.call_xenapi('VBD.create',
                self.vbd_rec).AndReturn("vbd_ref")
        self.session.call_xenapi('VBD.add_to_other_config', "vbd_ref",
                                 "osvol", "True")
        self.mock.ReplayAll()
        result = vm_utils.create_vbd(self.session, "vm_ref", "vdi_ref", 0,
                                     osvol=True)
        self.assertEqual(result, "vbd_ref")
        self.mock.VerifyAll()

    def test_create_vbd_extra_args(self):
        self.vbd_rec['VDI'] = 'OpaqueRef:NULL'
        self.vbd_rec['type'] = 'a'
        self.vbd_rec['mode'] = 'RO'
        self.vbd_rec['bootable'] = True
        self.vbd_rec['empty'] = True
        self.vbd_rec['unpluggable'] = False
        self.session.call_xenapi('VBD.create',
                self.vbd_rec).AndReturn("vbd_ref")
        self.mock.ReplayAll()

        result = vm_utils.create_vbd(self.session, "vm_ref", None, 0,
                vbd_type="a", read_only=True, bootable=True,
                empty=True, unpluggable=False)
        self.assertEqual(result, "vbd_ref")
        self.mock.VerifyAll()

    def test_attach_cd(self):
        self.mock.StubOutWithMock(vm_utils, 'create_vbd')

        vm_utils.create_vbd(self.session, "vm_ref", None, 1,
                vbd_type='cd', read_only=True, bootable=True,
                empty=True, unpluggable=False).AndReturn("vbd_ref")
        self.session.call_xenapi('VBD.insert', "vbd_ref", "vdi_ref")
        self.mock.ReplayAll()

        result = vm_utils.attach_cd(self.session, "vm_ref", "vdi_ref", 1)
        self.assertEqual(result, "vbd_ref")
        self.mock.VerifyAll()


class UnplugVbdTestCase(VMUtilsTestBase):
    @mock.patch.object(greenthread, 'sleep')
    def test_unplug_vbd_works(self, mock_sleep):
        session = _get_fake_session()
        vbd_ref = "vbd_ref"
        vm_ref = 'vm_ref'

        vm_utils.unplug_vbd(session, vbd_ref, vm_ref)

        session.call_xenapi.assert_called_once_with('VBD.unplug', vbd_ref)
        self.assertEqual(0, mock_sleep.call_count)

    def test_unplug_vbd_raises_unexpected_error(self):
        session = _get_fake_session()
        vbd_ref = "vbd_ref"
        vm_ref = 'vm_ref'
        session.call_xenapi.side_effect = test.TestingException()

        self.assertRaises(test.TestingException, vm_utils.unplug_vbd,
                          session, vm_ref, vbd_ref)
        self.assertEqual(1, session.call_xenapi.call_count)

    def test_unplug_vbd_already_detached_works(self):
        error = "DEVICE_ALREADY_DETACHED"
        session = _get_fake_session(error)
        vbd_ref = "vbd_ref"
        vm_ref = 'vm_ref'

        vm_utils.unplug_vbd(session, vbd_ref, vm_ref)
        self.assertEqual(1, session.call_xenapi.call_count)

    def test_unplug_vbd_already_raises_unexpected_xenapi_error(self):
        session = _get_fake_session("")
        vbd_ref = "vbd_ref"
        vm_ref = 'vm_ref'

        self.assertRaises(volume_utils.StorageError, vm_utils.unplug_vbd,
                          session, vbd_ref, vm_ref)
        self.assertEqual(1, session.call_xenapi.call_count)

    def _test_uplug_vbd_retries(self, mock_sleep, error):
        session = _get_fake_session(error)
        vbd_ref = "vbd_ref"
        vm_ref = 'vm_ref'

        self.assertRaises(volume_utils.StorageError, vm_utils.unplug_vbd,
                          session, vm_ref, vbd_ref)

        self.assertEqual(11, session.call_xenapi.call_count)
        self.assertEqual(10, mock_sleep.call_count)

    @mock.patch.object(greenthread, 'sleep')
    def test_uplug_vbd_retries_on_rejected(self, mock_sleep):
        self._test_uplug_vbd_retries(mock_sleep,
                                     "DEVICE_DETACH_REJECTED")

    @mock.patch.object(greenthread, 'sleep')
    def test_uplug_vbd_retries_on_internal_error(self, mock_sleep):
        self._test_uplug_vbd_retries(mock_sleep,
                                     "INTERNAL_ERROR")


class VDIOtherConfigTestCase(VMUtilsTestBase):
    """Tests to ensure that the code is populating VDI's `other_config`
    attribute with the correct metadta.
    """

    def setUp(self):
        super(VDIOtherConfigTestCase, self).setUp()

        class _FakeSession():
            def call_xenapi(self, operation, *args, **kwargs):
                # VDI.add_to_other_config -> VDI_add_to_other_config
                method = getattr(self, operation.replace('.', '_'), None)
                if method:
                    return method(*args, **kwargs)

                self.operation = operation
                self.args = args
                self.kwargs = kwargs

        self.session = _FakeSession()
        self.context = context.get_admin_context()
        self.fake_instance = {'uuid': 'aaaa-bbbb-cccc-dddd',
                              'name': 'myinstance'}

    def test_create_vdi(self):
        # Some images are registered with XenServer explicitly by calling
        # `create_vdi`
        vm_utils.create_vdi(self.session, 'sr_ref', self.fake_instance,
                            'myvdi', 'root', 1024, read_only=True)

        expected = {'nova_disk_type': 'root',
                    'nova_instance_uuid': 'aaaa-bbbb-cccc-dddd'}

        self.assertEqual(expected, self.session.args[0]['other_config'])

    def test_create_image(self):
        # Other images are registered implicitly when they are dropped into
        # the SR by a dom0 plugin or some other process
        self.flags(cache_images='none', group='xenserver')

        def fake_fetch_image(*args):
            return {'root': {'uuid': 'fake-uuid'}}

        self.stubs.Set(vm_utils, '_fetch_image', fake_fetch_image)

        other_config = {}

        def VDI_add_to_other_config(ref, key, value):
            other_config[key] = value

        # Stubbing on the session object and not class so we don't pollute
        # other tests
        self.session.VDI_add_to_other_config = VDI_add_to_other_config
        self.session.VDI_get_other_config = lambda vdi: {}

        vm_utils._create_image(self.context, self.session, self.fake_instance,
                'myvdi', 'image1', vm_utils.ImageType.DISK_VHD)

        expected = {'nova_disk_type': 'root',
                    'nova_instance_uuid': 'aaaa-bbbb-cccc-dddd'}

        self.assertEqual(expected, other_config)

    def test_import_migrated_vhds(self):
        # Migrated images should preserve the `other_config`
        other_config = {}

        def VDI_add_to_other_config(ref, key, value):
            other_config[key] = value

        def call_plugin_serialized(*args, **kwargs):
            return {'root': {'uuid': 'aaaa-bbbb-cccc-dddd'}}

        # Stubbing on the session object and not class so we don't pollute
        # other tests
        self.session.VDI_add_to_other_config = VDI_add_to_other_config
        self.session.VDI_get_other_config = lambda vdi: {}
        self.session.call_plugin_serialized = call_plugin_serialized

        self.stubs.Set(vm_utils, 'get_sr_path', lambda *a, **k: None)
        self.stubs.Set(vm_utils, 'scan_default_sr', lambda *a, **k: None)

        vm_utils._import_migrated_vhds(self.session, self.fake_instance,
                                       "disk_label", "root", "vdi_label")

        expected = {'nova_disk_type': 'root',
                    'nova_instance_uuid': 'aaaa-bbbb-cccc-dddd'}

        self.assertEqual(expected, other_config)


class GenerateDiskTestCase(VMUtilsTestBase):
    def setUp(self):
        super(GenerateDiskTestCase, self).setUp()
        self.flags(disable_process_locking=True,
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        self.flags(connection_url='test_url',
                   connection_password='test_pass',
                   group='xenserver')
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)
        self.session = driver._session
        self.session.is_local_connection = False
        self.vm_ref = fake.create_vm("foo", "Running")

    def tearDown(self):
        super(GenerateDiskTestCase, self).tearDown()
        fake.destroy_vm(self.vm_ref)

    def _expect_parted_calls(self):
        self.mox.StubOutWithMock(utils, "execute")
        self.mox.StubOutWithMock(utils, "trycmd")
        self.mox.StubOutWithMock(vm_utils, "destroy_vdi")
        self.mox.StubOutWithMock(vm_utils.os.path, "exists")
        if self.session.is_local_connection:
            utils.execute('parted', '--script', '/dev/fakedev', 'mklabel',
                          'msdos', check_exit_code=False, run_as_root=True)
            utils.execute('parted', '--script', '/dev/fakedev', '--', 'mkpart',
                          'primary', '0', '-0',
                          check_exit_code=False, run_as_root=True)
            vm_utils.os.path.exists('/dev/mapper/fakedev1').AndReturn(True)
            utils.trycmd('kpartx', '-a', '/dev/fakedev',
                         discard_warnings=True, run_as_root=True)
        else:
            utils.execute('parted', '--script', '/dev/fakedev', 'mklabel',
                          'msdos', check_exit_code=True, run_as_root=True)
            utils.execute('parted', '--script', '/dev/fakedev', '--', 'mkpart',
                          'primary', '0', '-0',
                          check_exit_code=True, run_as_root=True)

    def _check_vdi(self, vdi_ref, check_attached=True):
        vdi_rec = self.session.call_xenapi("VDI.get_record", vdi_ref)
        self.assertEqual(str(10 * units.Mi), vdi_rec["virtual_size"])
        if check_attached:
            vbd_ref = vdi_rec["VBDs"][0]
            vbd_rec = self.session.call_xenapi("VBD.get_record", vbd_ref)
            self.assertEqual(self.vm_ref, vbd_rec['VM'])
        else:
            self.assertEqual(0, len(vdi_rec["VBDs"]))

    @test_xenapi.stub_vm_utils_with_vdi_attached_here
    def test_generate_disk_with_no_fs_given(self):
        self._expect_parted_calls()

        self.mox.ReplayAll()
        vdi_ref = vm_utils._generate_disk(self.session, {"uuid": "fake_uuid"},
            self.vm_ref, "2", "name", "user", 10, None)
        self._check_vdi(vdi_ref)

    @test_xenapi.stub_vm_utils_with_vdi_attached_here
    def test_generate_disk_swap(self):
        self._expect_parted_calls()
        utils.execute('mkswap', '/dev/fakedev1', run_as_root=True)

        self.mox.ReplayAll()
        vdi_ref = vm_utils._generate_disk(self.session, {"uuid": "fake_uuid"},
            self.vm_ref, "2", "name", "swap", 10, "linux-swap")
        self._check_vdi(vdi_ref)

    @test_xenapi.stub_vm_utils_with_vdi_attached_here
    def test_generate_disk_ephemeral(self):
        self._expect_parted_calls()
        utils.execute('mkfs', '-t', 'ext4', '/dev/fakedev1',
            run_as_root=True)

        self.mox.ReplayAll()
        vdi_ref = vm_utils._generate_disk(self.session, {"uuid": "fake_uuid"},
            self.vm_ref, "2", "name", "ephemeral", 10, "ext4")
        self._check_vdi(vdi_ref)

    @test_xenapi.stub_vm_utils_with_vdi_attached_here
    def test_generate_disk_ensure_cleanup_called(self):
        self._expect_parted_calls()
        utils.execute('mkfs', '-t', 'ext4', '/dev/fakedev1',
            run_as_root=True).AndRaise(test.TestingException)
        vm_utils.destroy_vdi(self.session,
            mox.IgnoreArg()).AndRaise(volume_utils.StorageError)

        self.mox.ReplayAll()
        self.assertRaises(test.TestingException, vm_utils._generate_disk,
            self.session, {"uuid": "fake_uuid"},
            self.vm_ref, "2", "name", "ephemeral", 10, "ext4")

    @test_xenapi.stub_vm_utils_with_vdi_attached_here
    def test_generate_disk_ephemeral_local_not_attached(self):
        self.session.is_local_connection = True
        self._expect_parted_calls()
        utils.execute('mkfs', '-t', 'ext4', '/dev/mapper/fakedev1',
            run_as_root=True)

        self.mox.ReplayAll()
        vdi_ref = vm_utils._generate_disk(self.session, {"uuid": "fake_uuid"},
            None, "2", "name", "ephemeral", 10, "ext4")
        self._check_vdi(vdi_ref, check_attached=False)


class GenerateEphemeralTestCase(VMUtilsTestBase):
    def setUp(self):
        super(GenerateEphemeralTestCase, self).setUp()
        self.session = "session"
        self.instance = "instance"
        self.vm_ref = "vm_ref"
        self.name_label = "name"
        self.ephemeral_name_label = "name ephemeral"
        self.userdevice = 4
        self.mox.StubOutWithMock(vm_utils, "_generate_disk")
        self.mox.StubOutWithMock(vm_utils, "safe_destroy_vdis")

    def test_get_ephemeral_disk_sizes_simple(self):
        result = vm_utils.get_ephemeral_disk_sizes(20)
        expected = [20]
        self.assertEqual(expected, list(result))

    def test_get_ephemeral_disk_sizes_three_disks_2000(self):
        result = vm_utils.get_ephemeral_disk_sizes(4030)
        expected = [2000, 2000, 30]
        self.assertEqual(expected, list(result))

    def test_get_ephemeral_disk_sizes_two_disks_1024(self):
        result = vm_utils.get_ephemeral_disk_sizes(2048)
        expected = [1024, 1024]
        self.assertEqual(expected, list(result))

    def _expect_generate_disk(self, size, device, name_label):
        vm_utils._generate_disk(self.session, self.instance, self.vm_ref,
            str(device), name_label, 'ephemeral',
            size * 1024, None).AndReturn(device)

    def test_generate_ephemeral_adds_one_disk(self):
        self._expect_generate_disk(20, self.userdevice,
                                   self.ephemeral_name_label)
        self.mox.ReplayAll()

        vm_utils.generate_ephemeral(self.session, self.instance, self.vm_ref,
            str(self.userdevice), self.name_label, 20)

    def test_generate_ephemeral_adds_multiple_disks(self):
        self._expect_generate_disk(2000, self.userdevice,
                                   self.ephemeral_name_label)
        self._expect_generate_disk(2000, self.userdevice + 1,
                                   self.ephemeral_name_label + " (1)")
        self._expect_generate_disk(30, self.userdevice + 2,
                                   self.ephemeral_name_label + " (2)")
        self.mox.ReplayAll()

        vm_utils.generate_ephemeral(self.session, self.instance, self.vm_ref,
            str(self.userdevice), self.name_label, 4030)

    def test_generate_ephemeral_cleans_up_on_error(self):
        self._expect_generate_disk(1024, self.userdevice,
                                   self.ephemeral_name_label)
        self._expect_generate_disk(1024, self.userdevice + 1,
                                   self.ephemeral_name_label + " (1)")

        vm_utils._generate_disk(self.session, self.instance, self.vm_ref,
            str(self.userdevice + 2), "name ephemeral (2)", 'ephemeral',
            units.Mi, None).AndRaise(exception.NovaException)

        vm_utils.safe_destroy_vdis(self.session, [4, 5])

        self.mox.ReplayAll()

        self.assertRaises(exception.NovaException, vm_utils.generate_ephemeral,
            self.session, self.instance, self.vm_ref,
            str(self.userdevice), self.name_label, 4096)


class FakeFile(object):
    def __init__(self):
        self._file_operations = []

    def seek(self, offset):
        self._file_operations.append((self.seek, offset))


class StreamDiskTestCase(VMUtilsTestBase):
    def setUp(self):
        import __builtin__
        super(StreamDiskTestCase, self).setUp()
        self.mox.StubOutWithMock(vm_utils.utils, 'make_dev_path')
        self.mox.StubOutWithMock(vm_utils.utils, 'temporary_chown')
        self.mox.StubOutWithMock(vm_utils, '_write_partition')

        # NOTE(matelakat): This might hide the fail reason, as test runners
        # are unhappy with a mocked out open.
        self.mox.StubOutWithMock(__builtin__, 'open')
        self.image_service_func = self.mox.CreateMockAnything()

    def test_non_ami(self):
        fake_file = FakeFile()

        vm_utils.utils.make_dev_path('dev').AndReturn('some_path')
        vm_utils.utils.temporary_chown(
            'some_path').AndReturn(contextified(None))
        open('some_path', 'wb').AndReturn(contextified(fake_file))
        self.image_service_func(fake_file)

        self.mox.ReplayAll()

        vm_utils._stream_disk("session", self.image_service_func,
                              vm_utils.ImageType.KERNEL, None, 'dev')

        self.assertEqual([(fake_file.seek, 0)], fake_file._file_operations)

    def test_ami_disk(self):
        fake_file = FakeFile()

        vm_utils._write_partition("session", 100, 'dev')
        vm_utils.utils.make_dev_path('dev').AndReturn('some_path')
        vm_utils.utils.temporary_chown(
            'some_path').AndReturn(contextified(None))
        open('some_path', 'wb').AndReturn(contextified(fake_file))
        self.image_service_func(fake_file)

        self.mox.ReplayAll()

        vm_utils._stream_disk("session", self.image_service_func,
                              vm_utils.ImageType.DISK, 100, 'dev')

        self.assertEqual(
            [(fake_file.seek, vm_utils.MBR_SIZE_BYTES)],
            fake_file._file_operations)


class VMUtilsSRPath(VMUtilsTestBase):
    def setUp(self):
        super(VMUtilsSRPath, self).setUp()
        self.flags(disable_process_locking=True,
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        self.flags(connection_url='test_url',
                   connection_password='test_pass',
                   group='xenserver')
        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)
        self.session = driver._session
        self.session.is_local_connection = False

    def test_defined(self):
        self.mox.StubOutWithMock(vm_utils, "safe_find_sr")
        self.mox.StubOutWithMock(self.session, "call_xenapi")

        vm_utils.safe_find_sr(self.session).AndReturn("sr_ref")
        self.session.host_ref = "host_ref"
        self.session.call_xenapi('PBD.get_all_records_where',
            'field "host"="host_ref" and field "SR"="sr_ref"').AndReturn(
            {'pbd_ref': {'device_config': {'path': 'sr_path'}}})

        self.mox.ReplayAll()
        self.assertEqual(vm_utils.get_sr_path(self.session), "sr_path")

    def test_default(self):
        self.mox.StubOutWithMock(vm_utils, "safe_find_sr")
        self.mox.StubOutWithMock(self.session, "call_xenapi")

        vm_utils.safe_find_sr(self.session).AndReturn("sr_ref")
        self.session.host_ref = "host_ref"
        self.session.call_xenapi('PBD.get_all_records_where',
            'field "host"="host_ref" and field "SR"="sr_ref"').AndReturn(
            {'pbd_ref': {'device_config': {}}})
        self.session.call_xenapi("SR.get_record", "sr_ref").AndReturn(
            {'uuid': 'sr_uuid', 'type': 'ext'})
        self.mox.ReplayAll()
        self.assertEqual(vm_utils.get_sr_path(self.session),
                         "/var/run/sr-mount/sr_uuid")


class CreateKernelRamdiskTestCase(VMUtilsTestBase):
    def setUp(self):
        super(CreateKernelRamdiskTestCase, self).setUp()
        self.context = "context"
        self.session = FakeSession()
        self.instance = {"kernel_id": None, "ramdisk_id": None}
        self.name_label = "name"
        self.mox.StubOutWithMock(self.session, "call_plugin")
        self.mox.StubOutWithMock(uuid, "uuid4")
        self.mox.StubOutWithMock(vm_utils, "_fetch_disk_image")

    def test_create_kernel_and_ramdisk_no_create(self):
        self.mox.ReplayAll()
        result = vm_utils.create_kernel_and_ramdisk(self.context,
                    self.session, self.instance, self.name_label)
        self.assertEqual((None, None), result)

    def test_create_kernel_and_ramdisk_create_both_cached(self):
        kernel_id = "kernel"
        ramdisk_id = "ramdisk"
        self.instance["kernel_id"] = kernel_id
        self.instance["ramdisk_id"] = ramdisk_id

        args_kernel = {}
        args_kernel['cached-image'] = kernel_id
        args_kernel['new-image-uuid'] = "fake_uuid1"
        uuid.uuid4().AndReturn("fake_uuid1")
        self.session.call_plugin('kernel', 'create_kernel_ramdisk',
                                  args_kernel).AndReturn("k")

        args_ramdisk = {}
        args_ramdisk['cached-image'] = ramdisk_id
        args_ramdisk['new-image-uuid'] = "fake_uuid2"
        uuid.uuid4().AndReturn("fake_uuid2")
        self.session.call_plugin('kernel', 'create_kernel_ramdisk',
                                  args_ramdisk).AndReturn("r")

        self.mox.ReplayAll()
        result = vm_utils.create_kernel_and_ramdisk(self.context,
                    self.session, self.instance, self.name_label)
        self.assertEqual(("k", "r"), result)

    def test_create_kernel_and_ramdisk_create_kernel_not_cached(self):
        kernel_id = "kernel"
        self.instance["kernel_id"] = kernel_id

        args_kernel = {}
        args_kernel['cached-image'] = kernel_id
        args_kernel['new-image-uuid'] = "fake_uuid1"
        uuid.uuid4().AndReturn("fake_uuid1")
        self.session.call_plugin('kernel', 'create_kernel_ramdisk',
                                  args_kernel).AndReturn("")

        kernel = {"kernel": {"file": "k"}}
        vm_utils._fetch_disk_image(self.context, self.session, self.instance,
                    self.name_label, kernel_id, 0).AndReturn(kernel)

        self.mox.ReplayAll()
        result = vm_utils.create_kernel_and_ramdisk(self.context,
                    self.session, self.instance, self.name_label)
        self.assertEqual(("k", None), result)


class ScanSrTestCase(VMUtilsTestBase):
    @mock.patch.object(vm_utils, "_scan_sr")
    @mock.patch.object(vm_utils, "safe_find_sr")
    def test_scan_default_sr(self, mock_safe_find_sr, mock_scan_sr):
        mock_safe_find_sr.return_value = "sr_ref"

        self.assertEqual("sr_ref", vm_utils.scan_default_sr("fake_session"))

        mock_scan_sr.assert_called_once_with("fake_session", "sr_ref")

    def test_scan_sr_works(self):
        session = mock.Mock()
        vm_utils._scan_sr(session, "sr_ref")
        session.call_xenapi.assert_called_once_with('SR.scan', "sr_ref")

    def test_scan_sr_unknown_error_fails_once(self):
        session = mock.Mock()
        session.call_xenapi.side_effect = test.TestingException
        self.assertRaises(test.TestingException,
                          vm_utils._scan_sr, session, "sr_ref")
        session.call_xenapi.assert_called_once_with('SR.scan', "sr_ref")

    @mock.patch.object(greenthread, 'sleep')
    def test_scan_sr_known_error_retries_then_throws(self, mock_sleep):
        session = mock.Mock()

        class FakeException(Exception):
            details = ['SR_BACKEND_FAILURE_40', "", "", ""]

        session.XenAPI.Failure = FakeException
        session.call_xenapi.side_effect = FakeException

        self.assertRaises(FakeException,
                          vm_utils._scan_sr, session, "sr_ref")

        session.call_xenapi.assert_called_with('SR.scan', "sr_ref")
        self.assertEqual(4, session.call_xenapi.call_count)
        mock_sleep.assert_has_calls([mock.call(2), mock.call(4), mock.call(8)])

    @mock.patch.object(greenthread, 'sleep')
    def test_scan_sr_known_error_retries_then_succeeds(self, mock_sleep):
        session = mock.Mock()

        class FakeException(Exception):
            details = ['SR_BACKEND_FAILURE_40', "", "", ""]

        session.XenAPI.Failure = FakeException
        sr_scan_call_count = 0

        def fake_call_xenapi(*args):
            fake_call_xenapi.count += 1
            if fake_call_xenapi.count != 2:
                raise FakeException()

        fake_call_xenapi.count = 0
        session.call_xenapi.side_effect = fake_call_xenapi

        vm_utils._scan_sr(session, "sr_ref")

        session.call_xenapi.assert_called_with('SR.scan', "sr_ref")
        self.assertEqual(2, session.call_xenapi.call_count)
        mock_sleep.assert_called_once_with(2)


@mock.patch.object(flavors, 'extract_flavor',
                   return_value={
                            'memory_mb': 1024,
                            'vcpus': 1,
                            'vcpu_weight': 1.0,
                        })
class CreateVmTestCase(VMUtilsTestBase):
    def test_vss_provider(self, mock_extract):
        self.flags(vcpu_pin_set="2,3")
        session = _get_fake_session()
        instance = {
            "uuid": "uuid", "os_type": "windows"
        }

        vm_utils.create_vm(session, instance, "label",
                           "kernel", "ramdisk")

        vm_rec = {
            'VCPUs_params': {'cap': '0', 'mask': '2,3', 'weight': '1.0'},
            'PV_args': '',
            'memory_static_min': '0',
            'ha_restart_priority': '',
            'HVM_boot_policy': 'BIOS order',
            'PV_bootloader': '', 'tags': [],
            'VCPUs_max': '1',
            'memory_static_max': '1073741824',
            'actions_after_shutdown': 'destroy',
            'memory_dynamic_max': '1073741824',
            'user_version': '0',
            'xenstore_data': {'vm-data/allowvssprovider': 'false'},
            'blocked_operations': {},
            'is_a_template': False,
            'name_description': '',
            'memory_dynamic_min': '1073741824',
            'actions_after_crash': 'destroy',
            'memory_target': '1073741824',
            'PV_ramdisk': '',
            'PV_bootloader_args': '',
            'PCI_bus': '',
            'other_config': {'nova_uuid': 'uuid'},
            'name_label': 'label',
            'actions_after_reboot': 'restart',
            'VCPUs_at_startup': '1',
            'HVM_boot_params': {'order': 'dc'},
            'platform': {'nx': 'true', 'pae': 'true', 'apic': 'true',
                         'timeoffset': '0', 'viridian': 'true',
                         'acpi': 'true'},
            'PV_legacy_args': '',
            'PV_kernel': '',
            'affinity': '',
            'recommendations': '',
            'ha_always_run': False
        }
        session.call_xenapi.assert_called_once_with("VM.create", vm_rec)

    def test_invalid_cpu_mask_raises(self, mock_extract):
        self.flags(vcpu_pin_set="asdf")
        session = mock.Mock()
        instance = {
            "uuid": "uuid",
        }
        self.assertRaises(exception.Invalid,
                          vm_utils.create_vm,
                          session, instance, "label",
                          "kernel", "ramdisk")

    def test_destroy_vm(self, mock_extract):
        session = mock.Mock()
        instance = {
            "uuid": "uuid",
        }

        vm_utils.destroy_vm(session, instance, "vm_ref")

        session.VM.destroy.assert_called_once_with("vm_ref")

    def test_destroy_vm_silently_fails(self, mock_extract):
        session = mock.Mock()
        exc = test.TestingException()
        session.XenAPI.Failure = test.TestingException
        session.VM.destroy.side_effect = exc
        instance = {
            "uuid": "uuid",
        }

        vm_utils.destroy_vm(session, instance, "vm_ref")

        session.VM.destroy.assert_called_once_with("vm_ref")


class DetermineVmModeTestCase(VMUtilsTestBase):
    def test_determine_vm_mode_returns_xen_mode(self):
        instance = {"vm_mode": "xen"}
        self.assertEqual(vm_mode.XEN,
            vm_utils.determine_vm_mode(instance, None))

    def test_determine_vm_mode_returns_hvm_mode(self):
        instance = {"vm_mode": "hvm"}
        self.assertEqual(vm_mode.HVM,
            vm_utils.determine_vm_mode(instance, None))

    def test_determine_vm_mode_returns_xen_for_linux(self):
        instance = {"vm_mode": None, "os_type": "linux"}
        self.assertEqual(vm_mode.XEN,
            vm_utils.determine_vm_mode(instance, None))

    def test_determine_vm_mode_returns_hvm_for_windows(self):
        instance = {"vm_mode": None, "os_type": "windows"}
        self.assertEqual(vm_mode.HVM,
            vm_utils.determine_vm_mode(instance, None))

    def test_determine_vm_mode_returns_hvm_by_default(self):
        instance = {"vm_mode": None, "os_type": None}
        self.assertEqual(vm_mode.HVM,
            vm_utils.determine_vm_mode(instance, None))

    def test_determine_vm_mode_returns_xen_for_VHD(self):
        instance = {"vm_mode": None, "os_type": None}
        self.assertEqual(vm_mode.XEN,
            vm_utils.determine_vm_mode(instance, vm_utils.ImageType.DISK_VHD))

    def test_determine_vm_mode_returns_xen_for_DISK(self):
        instance = {"vm_mode": None, "os_type": None}
        self.assertEqual(vm_mode.XEN,
            vm_utils.determine_vm_mode(instance, vm_utils.ImageType.DISK))


class CallXenAPIHelpersTestCase(VMUtilsTestBase):
    def test_vm_get_vbd_refs(self):
        session = mock.Mock()
        session.call_xenapi.return_value = "foo"
        self.assertEqual("foo", vm_utils._vm_get_vbd_refs(session, "vm_ref"))
        session.call_xenapi.assert_called_once_with("VM.get_VBDs", "vm_ref")

    def test_vbd_get_rec(self):
        session = mock.Mock()
        session.call_xenapi.return_value = "foo"
        self.assertEqual("foo", vm_utils._vbd_get_rec(session, "vbd_ref"))
        session.call_xenapi.assert_called_once_with("VBD.get_record",
                                                    "vbd_ref")

    def test_vdi_get_rec(self):
        session = mock.Mock()
        session.call_xenapi.return_value = "foo"
        self.assertEqual("foo", vm_utils._vdi_get_rec(session, "vdi_ref"))
        session.call_xenapi.assert_called_once_with("VDI.get_record",
                                                    "vdi_ref")

    def test_vdi_snapshot(self):
        session = mock.Mock()
        session.call_xenapi.return_value = "foo"
        self.assertEqual("foo", vm_utils._vdi_snapshot(session, "vdi_ref"))
        session.call_xenapi.assert_called_once_with("VDI.snapshot",
                                                    "vdi_ref", {})

    def test_vdi_get_virtual_size(self):
        session = mock.Mock()
        session.call_xenapi.return_value = "123"
        self.assertEqual(123, vm_utils._vdi_get_virtual_size(session, "ref"))
        session.call_xenapi.assert_called_once_with("VDI.get_virtual_size",
                                                    "ref")

    @mock.patch.object(vm_utils, '_get_resize_func_name')
    def test_vdi_resize(self, mock_get_resize_func_name):
        session = mock.Mock()
        mock_get_resize_func_name.return_value = "VDI.fake"
        vm_utils._vdi_resize(session, "ref", 123)
        session.call_xenapi.assert_called_once_with("VDI.fake", "ref", "123")

    @mock.patch.object(vm_utils, '_vdi_resize')
    @mock.patch.object(vm_utils, '_vdi_get_virtual_size')
    def test_update_vdi_virtual_size_works(self, mock_get_size, mock_resize):
        mock_get_size.return_value = (1024 ** 3) - 1
        instance = {"uuid": "a"}

        vm_utils.update_vdi_virtual_size("s", instance, "ref", 1)

        mock_get_size.assert_called_once_with("s", "ref")
        mock_resize.assert_called_once_with("s", "ref", 1024 ** 3)

    @mock.patch.object(vm_utils, '_vdi_resize')
    @mock.patch.object(vm_utils, '_vdi_get_virtual_size')
    def test_update_vdi_virtual_size_skips_resize_down(self, mock_get_size,
                                                       mock_resize):
        mock_get_size.return_value = 1024 ** 3
        instance = {"uuid": "a"}

        vm_utils.update_vdi_virtual_size("s", instance, "ref", 1)

        mock_get_size.assert_called_once_with("s", "ref")
        self.assertFalse(mock_resize.called)

    @mock.patch.object(vm_utils, '_vdi_resize')
    @mock.patch.object(vm_utils, '_vdi_get_virtual_size')
    def test_update_vdi_virtual_size_raise_if_disk_big(self, mock_get_size,
                                                       mock_resize):
        mock_get_size.return_value = 1024 ** 3 + 1
        instance = {"uuid": "a"}

        self.assertRaises(exception.ResizeError,
                          vm_utils.update_vdi_virtual_size,
                          "s", instance, "ref", 1)

        mock_get_size.assert_called_once_with("s", "ref")
        self.assertFalse(mock_resize.called)


@mock.patch.object(vm_utils, '_vdi_get_rec')
@mock.patch.object(vm_utils, '_vbd_get_rec')
@mock.patch.object(vm_utils, '_vm_get_vbd_refs')
class GetVdiForVMTestCase(VMUtilsTestBase):
    def test_get_vdi_for_vm_safely(self, vm_get_vbd_refs,
                                   vbd_get_rec, vdi_get_rec):
        session = "session"

        vm_get_vbd_refs.return_value = ["a", "b"]
        vbd_get_rec.return_value = {'userdevice': '0', 'VDI': 'vdi_ref'}
        vdi_get_rec.return_value = {}

        result = vm_utils.get_vdi_for_vm_safely(session, "vm_ref")
        self.assertEqual(('vdi_ref', {}), result)

        vm_get_vbd_refs.assert_called_once_with(session, "vm_ref")
        vbd_get_rec.assert_called_once_with(session, "a")
        vdi_get_rec.assert_called_once_with(session, "vdi_ref")

    def test_get_vdi_for_vm_safely_fails(self, vm_get_vbd_refs,
                                         vbd_get_rec, vdi_get_rec):
        session = "session"

        vm_get_vbd_refs.return_value = ["a", "b"]
        vbd_get_rec.return_value = {'userdevice': '0', 'VDI': 'vdi_ref'}

        self.assertRaises(exception.NovaException,
                          vm_utils.get_vdi_for_vm_safely,
                          session, "vm_ref", userdevice='1')

        self.assertEqual([], vdi_get_rec.call_args_list)
        self.assertEqual(2, len(vbd_get_rec.call_args_list))


@mock.patch.object(vm_utils, '_vdi_get_uuid')
@mock.patch.object(vm_utils, '_vbd_get_rec')
@mock.patch.object(vm_utils, '_vm_get_vbd_refs')
class GetAllVdiForVMTestCase(VMUtilsTestBase):
    def _setup_get_all_vdi_uuids_for_vm(self, vm_get_vbd_refs,
                                       vbd_get_rec, vdi_get_uuid):
        def fake_vbd_get_rec(session, vbd_ref):
            return {'userdevice': vbd_ref, 'VDI': "vdi_ref_%s" % vbd_ref}

        def fake_vdi_get_uuid(session, vdi_ref):
            return vdi_ref

        vm_get_vbd_refs.return_value = ["0", "2"]
        vbd_get_rec.side_effect = fake_vbd_get_rec
        vdi_get_uuid.side_effect = fake_vdi_get_uuid

    def test_get_all_vdi_uuids_for_vm_works(self, vm_get_vbd_refs,
                                            vbd_get_rec, vdi_get_uuid):
        self._setup_get_all_vdi_uuids_for_vm(vm_get_vbd_refs,
                vbd_get_rec, vdi_get_uuid)

        result = vm_utils.get_all_vdi_uuids_for_vm('session', "vm_ref")
        expected = ['vdi_ref_0', 'vdi_ref_2']
        self.assertEqual(expected, list(result))

    def test_get_all_vdi_uuids_for_vm_finds_none(self, vm_get_vbd_refs,
                                                 vbd_get_rec, vdi_get_uuid):
        self._setup_get_all_vdi_uuids_for_vm(vm_get_vbd_refs,
                vbd_get_rec, vdi_get_uuid)

        result = vm_utils.get_all_vdi_uuids_for_vm('session', "vm_ref",
                                                   min_userdevice=1)
        expected = ["vdi_ref_2"]
        self.assertEqual(expected, list(result))


class GetAllVdisTestCase(VMUtilsTestBase):
    def test_get_all_vdis_in_sr(self):

        def fake_get_rec(record_type, ref):
            if ref == "2":
                return "vdi_rec_2"

        session = mock.Mock()
        session.call_xenapi.return_value = ["1", "2"]
        session.get_rec.side_effect = fake_get_rec

        sr_ref = "sr_ref"
        actual = list(vm_utils._get_all_vdis_in_sr(session, sr_ref))
        self.assertEqual(actual, [('2', 'vdi_rec_2')])

        session.call_xenapi.assert_called_once_with("SR.get_VDIs", sr_ref)


class VDIAttachedHere(VMUtilsTestBase):
    @mock.patch.object(vm_utils, 'destroy_vbd')
    @mock.patch.object(vm_utils, '_get_this_vm_ref')
    @mock.patch.object(vm_utils, 'create_vbd')
    @mock.patch.object(vm_utils, '_remap_vbd_dev')
    @mock.patch.object(vm_utils, '_wait_for_device')
    @mock.patch.object(utils, 'execute')
    def test_sync_called(self, mock_execute, mock_wait_for_device,
                         mock_remap_vbd_dev, mock_create_vbd,
                         mock_get_this_vm_ref, mock_destroy_vbd):
        session = _get_fake_session()
        with vm_utils.vdi_attached_here(session, 'vdi_ref'):
            pass
        mock_execute.assert_called_with('sync', run_as_root=True)


class SnapshotAttachedHereTestCase(VMUtilsTestBase):
    @mock.patch.object(vm_utils, '_snapshot_attached_here_impl')
    def test_snapshot_attached_here(self, mock_impl):
        def fake_impl(session, instance, vm_ref, label, userdevice,
                      post_snapshot_callback):
            self.assertEqual("session", session)
            self.assertEqual("instance", instance)
            self.assertEqual("vm_ref", vm_ref)
            self.assertEqual("label", label)
            self.assertEqual('0', userdevice)
            self.assertIsNone(post_snapshot_callback)
            yield "fake"

        mock_impl.side_effect = fake_impl

        with vm_utils.snapshot_attached_here("session", "instance", "vm_ref",
                                             "label") as result:
            self.assertEqual("fake", result)

        mock_impl.assert_called_once_with("session", "instance", "vm_ref",
                                          "label", '0', None)

    @mock.patch.object(vm_utils, 'safe_destroy_vdis')
    @mock.patch.object(vm_utils, '_walk_vdi_chain')
    @mock.patch.object(vm_utils, '_wait_for_vhd_coalesce')
    @mock.patch.object(vm_utils, '_vdi_get_uuid')
    @mock.patch.object(vm_utils, '_vdi_snapshot')
    @mock.patch.object(vm_utils, '_get_vhd_parent_uuid')
    @mock.patch.object(vm_utils, 'get_vdi_for_vm_safely')
    def test_snapshot_attached_here_impl(self, mock_get_vdi_for_vm_safely,
            mock_get_vhd_parent_uuid, mock_vdi_snapshot, mock_vdi_get_uuid,
            mock_wait_for_vhd_coalesce, mock_walk_vdi_chain,
            mock_safe_destroy_vdis):
        session = "session"
        instance = {"uuid": "uuid"}
        mock_callback = mock.Mock()

        mock_get_vdi_for_vm_safely.return_value = ("vdi_ref",
                                                   {"SR": "sr_ref"})
        mock_get_vhd_parent_uuid.return_value = "original_uuid"
        mock_vdi_snapshot.return_value = "snap_ref"
        mock_vdi_get_uuid.return_value = "snap_uuid"
        mock_walk_vdi_chain.return_value = [{"uuid": "a"}, {"uuid": "b"}]

        try:
            with vm_utils.snapshot_attached_here(session, instance, "vm_ref",
                    "label", '2', mock_callback) as result:
                self.assertEqual(["a", "b"], result)
                raise test.TestingException()
            self.assertTrue(False)
        except test.TestingException:
            pass

        mock_get_vdi_for_vm_safely.assert_called_once_with(session, "vm_ref",
                                                           '2')
        mock_get_vhd_parent_uuid.assert_called_once_with(session, "vdi_ref")
        mock_vdi_snapshot.assert_called_once_with(session, "vdi_ref")
        mock_wait_for_vhd_coalesce.assert_called_once_with(session, instance,
                "sr_ref", "vdi_ref", "original_uuid")
        mock_vdi_get_uuid.assert_called_once_with(session, "snap_ref")
        mock_walk_vdi_chain.assert_called_once_with(session, "snap_uuid")
        mock_callback.assert_called_once_with(
                task_state="image_pending_upload")
        mock_safe_destroy_vdis.assert_called_once_with(session, ["snap_ref"])

    @mock.patch.object(greenthread, 'sleep')
    @mock.patch.object(vm_utils, '_get_vhd_parent_uuid')
    @mock.patch.object(vm_utils, '_another_child_vhd')
    @mock.patch.object(vm_utils, '_scan_sr')
    def test_wait_for_vhd_coalesce(self, mock_scan_sr, mock_another_child_vhd,
            mock_get_vhd_parent_uuid, mock_sleep):

        cfg.CONF.import_opt('vhd_coalesce_max_attempts',
                            'nova.virt.xenapi.driver', group="xenserver")
        max_sr_scan_count = cfg.CONF.xenserver.vhd_coalesce_max_attempts - 1

        vhd_chain = ['vdi_base_ref', 'vdi_coalescable_ref', 'vdi_leaf_ref']
        instance = {"uuid": "uuid"}
        sr_ref = 'sr_ref'
        session = mock.Mock()

        def fake_scan_sr(session, sr_ref):
            fake_scan_sr.count += 1
            if fake_scan_sr.count == max_sr_scan_count:
                vhd_chain.remove('vdi_coalescable_ref')

        def fake_get_vhd_parent_uuid(session, vdi_ref):
            index = vhd_chain.index(vdi_ref)
            if index > 0:
                return vhd_chain[index - 1].replace('ref', 'uuid')
            return None

        def fake_call_xenapi(method, *args):
            if method == 'VDI.get_by_uuid':
                return args[0].replace('uuid', 'ref')

        fake_scan_sr.count = 0
        fake_scan_sr.running = True
        mock_scan_sr.side_effect = fake_scan_sr
        session.call_xenapi.side_effect = fake_call_xenapi
        mock_get_vhd_parent_uuid.side_effect = fake_get_vhd_parent_uuid

        mock_another_child_vhd.return_value = False

        self.assertEqual(('vdi_base_uuid', None),
             vm_utils._wait_for_vhd_coalesce(session, instance, sr_ref,
                                             'vdi_leaf_ref', 'vdi_base_uuid'))
        self.assertEqual(max_sr_scan_count, mock_scan_sr.call_count)
        session.call_plugin_serialized.has_calls(session, "vdi_ref")
        # We'll sleep one fewer times than we scan the SR due to
        # the scan at the start
        self.assertEqual(max_sr_scan_count - 1, mock_sleep.call_count)


class ImportMigratedDisksTestCase(VMUtilsTestBase):
    @mock.patch.object(vm_utils, '_import_migrate_ephemeral_disks')
    @mock.patch.object(vm_utils, '_import_migrated_root_disk')
    def test_import_all_migrated_disks(self, mock_root, mock_ephemeral):
        session = "session"
        instance = "instance"
        mock_root.return_value = "root_vdi"
        mock_ephemeral.return_value = ["a", "b"]

        result = vm_utils.import_all_migrated_disks(session, instance)

        expected = {'root': 'root_vdi', 'ephemerals': ["a", "b"]}
        self.assertEqual(expected, result)
        mock_root.assert_called_once_with(session, instance)
        mock_ephemeral.assert_called_once_with(session, instance)

    @mock.patch.object(vm_utils, '_import_migrated_vhds')
    def test_import_migrated_root_disk(self, mock_migrate):
        mock_migrate.return_value = "foo"
        instance = {"uuid": "uuid", "name": "name"}

        result = vm_utils._import_migrated_root_disk("s", instance)

        self.assertEqual("foo", result)
        mock_migrate.assert_called_once_with("s", instance, "uuid", "root",
                                             "name")

    @mock.patch.object(vm_utils, '_import_migrated_vhds')
    def test_import_migrate_ephemeral_disks(self, mock_migrate):
        mock_migrate.return_value = "foo"
        instance = {"uuid": "uuid", "name": "name", "ephemeral_gb": 4000}

        result = vm_utils._import_migrate_ephemeral_disks("s", instance)

        self.assertEqual({'4': 'foo', '5': 'foo'}, result)
        expected_calls = [mock.call("s", instance, "uuid_ephemeral_1",
                                    "ephemeral", "name ephemeral (1)"),
                          mock.call("s", instance, "uuid_ephemeral_2",
                                    "ephemeral", "name ephemeral (2)")]
        self.assertEqual(expected_calls, mock_migrate.call_args_list)

    @mock.patch.object(vm_utils, '_set_vdi_info')
    @mock.patch.object(vm_utils, 'scan_default_sr')
    @mock.patch.object(vm_utils, 'get_sr_path')
    def test_import_migrated_vhds(self, mock_get_sr_path, mock_scan_sr,
                                  mock_set_info):
        session = mock.Mock()
        instance = {"uuid": "uuid"}
        session.call_plugin_serialized.return_value = {"root": {"uuid": "a"}}
        session.call_xenapi.return_value = "vdi_ref"
        mock_get_sr_path.return_value = "sr_path"

        result = vm_utils._import_migrated_vhds(session, instance,
                'chain_label', 'disk_type', 'vdi_label')

        expected = {'uuid': "a", 'ref': "vdi_ref"}
        self.assertEqual(expected, result)
        mock_get_sr_path.assert_called_once_with(session)
        session.call_plugin_serialized.assert_called_once_with('migration',
                'move_vhds_into_sr', instance_uuid='chain_label',
                sr_path='sr_path', uuid_stack=mock.ANY)
        mock_scan_sr.assert_called_once_with(session)
        session.call_xenapi.assert_called_once_with('VDI.get_by_uuid', 'a')
        mock_set_info.assert_called_once_with(session, 'vdi_ref', 'disk_type',
                'vdi_label', 'disk_type', instance)

    def test_get_vhd_parent_uuid_rec_provided(self):
        session = mock.Mock()
        vdi_ref = 'vdi_ref'
        vdi_rec = {'sm_config': {}}
        self.assertIsNone(vm_utils._get_vhd_parent_uuid(session,
                                                             vdi_ref,
                                                             vdi_rec))
        self.assertFalse(session.call_xenapi.called)


class MigrateVHDTestCase(VMUtilsTestBase):
    def _assert_transfer_called(self, session, label):
        session.call_plugin_serialized.assert_called_once_with(
                'migration', 'transfer_vhd', instance_uuid=label, host="dest",
                vdi_uuid="vdi_uuid", sr_path="sr_path", seq_num=2)

    def test_migrate_vhd_root(self):
        session = mock.Mock()
        instance = {"uuid": "a"}

        vm_utils.migrate_vhd(session, instance, "vdi_uuid", "dest",
                             "sr_path", 2)

        self._assert_transfer_called(session, "a")

    def test_migrate_vhd_ephemeral(self):
        session = mock.Mock()
        instance = {"uuid": "a"}

        vm_utils.migrate_vhd(session, instance, "vdi_uuid", "dest",
                             "sr_path", 2, 2)

        self._assert_transfer_called(session, "a_ephemeral_2")

    def test_migrate_vhd_converts_exceptions(self):
        session = mock.Mock()
        session.XenAPI.Failure = test.TestingException
        session.call_plugin_serialized.side_effect = test.TestingException()
        instance = {"uuid": "a"}

        self.assertRaises(exception.MigrationError, vm_utils.migrate_vhd,
                          session, instance, "vdi_uuid", "dest", "sr_path", 2)
        self._assert_transfer_called(session, "a")


class StripBaseMirrorTestCase(VMUtilsTestBase):
    def test_strip_base_mirror_from_vdi_works(self):
        session = mock.Mock()
        vm_utils._try_strip_base_mirror_from_vdi(session, "vdi_ref")
        session.call_xenapi.assert_called_once_with(
                "VDI.remove_from_sm_config", "vdi_ref", "base_mirror")

    def test_strip_base_mirror_from_vdi_hides_error(self):
        session = mock.Mock()
        session.XenAPI.Failure = test.TestingException
        session.call_xenapi.side_effect = test.TestingException()

        vm_utils._try_strip_base_mirror_from_vdi(session, "vdi_ref")

        session.call_xenapi.assert_called_once_with(
                "VDI.remove_from_sm_config", "vdi_ref", "base_mirror")

    @mock.patch.object(vm_utils, '_try_strip_base_mirror_from_vdi')
    def test_strip_base_mirror_from_vdis(self, mock_strip):
        def call_xenapi(method, arg):
            if method == "VM.get_VBDs":
                return ['VBD_ref_1', 'VBD_ref_2']
            if method == "VBD.get_VDI":
                return 'VDI' + arg[3:]
            return "Unexpected call_xenapi: %s.%s" % (method, arg)

        session = mock.Mock()
        session.call_xenapi.side_effect = call_xenapi

        vm_utils.strip_base_mirror_from_vdis(session, "vm_ref")

        expected = [mock.call('VM.get_VBDs', "vm_ref"),
                    mock.call('VBD.get_VDI', "VBD_ref_1"),
                    mock.call('VBD.get_VDI', "VBD_ref_2")]
        self.assertEqual(expected, session.call_xenapi.call_args_list)

        expected = [mock.call(session, "VDI_ref_1"),
                    mock.call(session, "VDI_ref_2")]
        self.assertEqual(expected, mock_strip.call_args_list)


class DeviceIdTestCase(VMUtilsTestBase):
    def test_device_id_is_none_if_not_specified_in_meta_data(self):
        image_meta = {}
        session = mock.Mock()
        session.product_version = (6, 1, 0)
        self.assertIsNone(vm_utils.get_vm_device_id(session, image_meta))

    def test_get_device_id_if_hypervisor_version_is_greater_than_6_1(self):
        image_meta = {'xenapi_device_id': '0002'}
        session = mock.Mock()
        session.product_version = (6, 2, 0)
        self.assertEqual('0002',
                         vm_utils.get_vm_device_id(session, image_meta))
        session.product_version = (6, 3, 1)
        self.assertEqual('0002',
                         vm_utils.get_vm_device_id(session, image_meta))

    def test_raise_exception_if_device_id_not_supported_by_hyp_version(self):
        image_meta = {'xenapi_device_id': '0002'}
        session = mock.Mock()
        session.product_version = (6, 0)
        exc = self.assertRaises(exception.NovaException,
                                vm_utils.get_vm_device_id, session, image_meta)
        self.assertEqual("Device id 0002 specified is not supported by "
                         "hypervisor version (6, 0)", exc.message)
        session.product_version = ('6a')
        exc = self.assertRaises(exception.NovaException,
                                vm_utils.get_vm_device_id, session, image_meta)
        self.assertEqual("Device id 0002 specified is not supported by "
                         "hypervisor version 6a", exc.message)


class CreateVmRecordTestCase(VMUtilsTestBase):
    @mock.patch.object(flavors, 'extract_flavor')
    def test_create_vm_record_linux(self, mock_extract_flavor):
        instance = {"uuid": "uuid123", "os_type": "linux"}
        self._test_create_vm_record(mock_extract_flavor, instance, False)

    @mock.patch.object(flavors, 'extract_flavor')
    def test_create_vm_record_windows(self, mock_extract_flavor):
        instance = {"uuid": "uuid123", "os_type": "windows"}
        self._test_create_vm_record(mock_extract_flavor, instance, True)

    def _test_create_vm_record(self, mock_extract_flavor, instance,
                               is_viridian):
        session = _get_fake_session()
        flavor = {"memory_mb": 1024, "vcpus": 1, "vcpu_weight": 2}
        mock_extract_flavor.return_value = flavor

        vm_utils.create_vm(session, instance, "name", "kernel", "ramdisk",
                           device_id="0002")

        is_viridian_str = str(is_viridian).lower()

        expected_vm_rec = {
            'VCPUs_params': {'cap': '0', 'weight': '2'},
            'PV_args': '',
            'memory_static_min': '0',
            'ha_restart_priority': '',
            'HVM_boot_policy': 'BIOS order',
            'PV_bootloader': '',
            'tags': [],
            'VCPUs_max': '1',
            'memory_static_max': '1073741824',
            'actions_after_shutdown': 'destroy',
            'memory_dynamic_max': '1073741824',
            'user_version': '0',
            'xenstore_data': {'vm-data/allowvssprovider': 'false'},
            'blocked_operations': {},
            'is_a_template': False,
            'name_description': '',
            'memory_dynamic_min': '1073741824',
            'actions_after_crash': 'destroy',
            'memory_target': '1073741824',
            'PV_ramdisk': '',
            'PV_bootloader_args': '',
            'PCI_bus': '',
            'other_config': {'nova_uuid': 'uuid123'},
            'name_label': 'name',
            'actions_after_reboot': 'restart',
            'VCPUs_at_startup': '1',
            'HVM_boot_params': {'order': 'dc'},
            'platform': {'nx': 'true', 'pae': 'true', 'apic': 'true',
                         'timeoffset': '0', 'viridian': is_viridian_str,
                         'acpi': 'true', 'device_id': '0002'},
            'PV_legacy_args': '',
            'PV_kernel': '',
            'affinity': '',
            'recommendations': '',
            'ha_always_run': False}

        session.call_xenapi.assert_called_with('VM.create', expected_vm_rec)

    def test_list_vms(self):
        self.flags(disable_process_locking=True,
                   instance_name_template='%d',
                   firewall_driver='nova.virt.xenapi.firewall.'
                                   'Dom0IptablesFirewallDriver')
        self.flags(connection_url='test_url',
                   connection_password='test_pass',
                   group='xenserver')

        fake.create_vm("foo1", "Halted")
        vm_ref = fake.create_vm("foo2", "Running")

        stubs.stubout_session(self.stubs, fake.SessionBase)
        driver = xenapi_conn.XenAPIDriver(False)

        result = list(vm_utils.list_vms(driver._session))

        # Will have 3 VMs - but one is Dom0 and one is not running on the host
        self.assertEqual(len(driver._session.call_xenapi('VM.get_all')), 3)
        self.assertEqual(len(result), 1)

        result_keys = [key for (key, value) in result]

        self.assertIn(vm_ref, result_keys)


class ResizeFunctionTestCase(test.NoDBTestCase):
    def _call_get_resize_func_name(self, brand, version):
        session = mock.Mock()
        session.product_brand = brand
        session.product_version = version

        return vm_utils._get_resize_func_name(session)

    def _test_is_resize(self, brand, version):
        result = self._call_get_resize_func_name(brand, version)
        self.assertEqual("VDI.resize", result)

    def _test_is_resize_online(self, brand, version):
        result = self._call_get_resize_func_name(brand, version)
        self.assertEqual("VDI.resize_online", result)

    def test_xenserver_5_5(self):
        self._test_is_resize_online("XenServer", (5, 5, 0))

    def test_xenserver_6_0(self):
        self._test_is_resize("XenServer", (6, 0, 0))

    def test_xcp_1_1(self):
        self._test_is_resize_online("XCP", (1, 1, 0))

    def test_xcp_1_2(self):
        self._test_is_resize("XCP", (1, 2, 0))

    def test_xcp_2_0(self):
        self._test_is_resize("XCP", (2, 0, 0))

    def test_random_brand(self):
        self._test_is_resize("asfd", (1, 1, 0))

    def test_default(self):
        self._test_is_resize(None, None)

    def test_empty(self):
        self._test_is_resize("", "")

    def test_bad_version(self):
        self._test_is_resize("XenServer", "asdf")


class VMInfoTests(VMUtilsTestBase):
    def setUp(self):
        super(VMInfoTests, self).setUp()
        self.session = mock.Mock()

    def test_get_power_state_valid(self):
        # Save on test setup calls by having these simple tests in one method
        self.session.call_xenapi.return_value = "Running"
        self.assertEqual(vm_utils.get_power_state(self.session, "ref"),
                         power_state.RUNNING)

        self.session.call_xenapi.return_value = "Halted"
        self.assertEqual(vm_utils.get_power_state(self.session, "ref"),
                         power_state.SHUTDOWN)

        self.session.call_xenapi.return_value = "Paused"
        self.assertEqual(vm_utils.get_power_state(self.session, "ref"),
                         power_state.PAUSED)

        self.session.call_xenapi.return_value = "Suspended"
        self.assertEqual(vm_utils.get_power_state(self.session, "ref"),
                         power_state.SUSPENDED)

        self.session.call_xenapi.return_value = "Crashed"
        self.assertEqual(vm_utils.get_power_state(self.session, "ref"),
                         power_state.CRASHED)

    def test_get_power_state_invalid(self):
        self.session.call_xenapi.return_value = "Invalid"
        self.assertRaises(KeyError,
                          vm_utils.get_power_state, self.session, "ref")

    _XAPI_record = {'power_state': 'Running',
                    'memory_static_max': str(10 << 10),
                    'memory_dynamic_max': str(9 << 10),
                    'VCPUs_max': '5'}

    def test_compile_info(self):

        def call_xenapi(method, *args):
            if method.startswith('VM.get_') and args[0] == 'dummy':
                return self._XAPI_record[method[7:]]

        self.session.call_xenapi.side_effect = call_xenapi

        expected = {'state': power_state.RUNNING,
                    'max_mem': 10L,
                    'mem': 9L,
                    'num_cpu': '5',
                    'cpu_time': 0}

        self.assertEqual(vm_utils.compile_info(self.session, "dummy"),
                         expected)
