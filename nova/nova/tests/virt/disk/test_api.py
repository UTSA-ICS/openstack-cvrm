# Copyright 2012 OpenStack Foundation
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

import tempfile

import fixtures

from nova.openstack.common import processutils
from nova import test
from nova import utils
from nova.virt.disk import api
from nova.virt.disk.mount import api as mount


class FakeMount(object):
    device = None

    @staticmethod
    def instance_for_format(imgfile, mountdir, partition, imgfmt):
        return FakeMount()

    def get_dev(self):
        pass

    def unget_dev(self):
        pass


class APITestCase(test.NoDBTestCase):

    def setUp(self):
        super(APITestCase, self).setUp()

    def test_can_resize_need_fs_type_specified(self):
        # NOTE(mikal): Bug 1094373 saw a regression where we failed to
        # treat a failure to mount as a failure to be able to resize the
        # filesystem
        def _fake_get_disk_size(path):
            return 10
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.api.get_disk_size', _fake_get_disk_size))

        def fake_trycmd(*args, **kwargs):
            return '', 'broken'
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        def fake_returns_true(*args, **kwargs):
            return True
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.mount.nbd.NbdMount.get_dev',
                fake_returns_true))
        self.useFixture(fixtures.MonkeyPatch(
                'nova.virt.disk.mount.nbd.NbdMount.map_dev',
                fake_returns_true))

        # Force the use of localfs, which is what was used during the failure
        # reported in the bug
        def fake_import_fails(*args, **kwargs):
            raise Exception('Failed')
        self.useFixture(fixtures.MonkeyPatch(
                'nova.openstack.common.importutils.import_module',
                fake_import_fails))

        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        self.assertFalse(api.is_image_partitionless(imgfile, use_cow=True))

    def test_resize2fs_success(self):
        imgfile = tempfile.NamedTemporaryFile()

        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('e2fsck',
                      '-fp',
                      imgfile,
                      check_exit_code=[0, 1, 2],
                      run_as_root=False)
        utils.execute('resize2fs',
                      imgfile,
                      check_exit_code=False,
                      run_as_root=False)

        self.mox.ReplayAll()
        api.resize2fs(imgfile)

    def test_resize2fs_e2fsck_fails(self):
        imgfile = tempfile.NamedTemporaryFile()

        self.mox.StubOutWithMock(utils, 'execute')
        utils.execute('e2fsck',
                      '-fp',
                      imgfile,
                      check_exit_code=[0, 1, 2],
                      run_as_root=False).AndRaise(
                          processutils.ProcessExecutionError("fs error"))
        self.mox.ReplayAll()
        api.resize2fs(imgfile)

    def test_extend_qcow_success(self):
        imgfile = tempfile.NamedTemporaryFile()
        imgsize = 10
        device = "/dev/sdh"
        use_cow = True

        self.flags(resize_fs_using_block_device=True)
        mounter = FakeMount.instance_for_format(
            imgfile, None, None, 'qcow2')
        mounter.device = device

        self.mox.StubOutWithMock(api, 'can_resize_image')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(api, 'is_image_partitionless')
        self.mox.StubOutWithMock(mounter, 'get_dev')
        self.mox.StubOutWithMock(mounter, 'unget_dev')
        self.mox.StubOutWithMock(api, 'resize2fs')
        self.mox.StubOutWithMock(mount.Mount, 'instance_for_format')

        api.can_resize_image(imgfile, imgsize).AndReturn(True)
        utils.execute('qemu-img', 'resize', imgfile, imgsize)
        api.is_image_partitionless(imgfile, use_cow).AndReturn(True)
        mount.Mount.instance_for_format(
            imgfile, None, None, 'qcow2').AndReturn(mounter)
        mounter.get_dev().AndReturn(True)
        api.resize2fs(mounter.device, run_as_root=True, check_exit_code=[0])
        mounter.unget_dev()

        self.mox.ReplayAll()
        api.extend(imgfile, imgsize, use_cow=use_cow)

    def test_extend_raw_success(self):
        imgfile = tempfile.NamedTemporaryFile()
        imgsize = 10
        device = "/dev/sdh"
        use_cow = False

        self.mox.StubOutWithMock(api, 'can_resize_image')
        self.mox.StubOutWithMock(utils, 'execute')
        self.mox.StubOutWithMock(api, 'is_image_partitionless')
        self.mox.StubOutWithMock(api, 'resize2fs')

        api.can_resize_image(imgfile, imgsize).AndReturn(True)
        utils.execute('qemu-img', 'resize', imgfile, imgsize)
        api.is_image_partitionless(imgfile, use_cow).AndReturn(True)
        api.resize2fs(imgfile, run_as_root=False, check_exit_code=[0])

        self.mox.ReplayAll()
        api.extend(imgfile, imgsize, use_cow=use_cow)
