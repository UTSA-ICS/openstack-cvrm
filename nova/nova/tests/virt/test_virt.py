# Copyright 2011 Isaku Yamahata
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

import io
import os

import mock

from nova import test
from nova import utils
from nova.virt.disk import api as disk_api
from nova.virt.disk.mount import api as mount
from nova.virt import driver

PROC_MOUNTS_CONTENTS = """rootfs / rootfs rw 0 0
sysfs /sys sysfs rw,nosuid,nodev,noexec,relatime 0 0
proc /proc proc rw,nosuid,nodev,noexec,relatime 0 0
udev /dev devtmpfs rw,relatime,size=1013160k,nr_inodes=253290,mode=755 0 0
devpts /dev/pts devpts rw,nosuid,noexec,relatime,gid=5,mode=620 0 0
tmpfs /run tmpfs rw,nosuid,relatime,size=408904k,mode=755 0 0"""


class TestVirtDriver(test.NoDBTestCase):
    def test_block_device(self):
        swap = {'device_name': '/dev/sdb',
                'swap_size': 1}
        ephemerals = [{'num': 0,
                       'virtual_name': 'ephemeral0',
                       'device_name': '/dev/sdc1',
                       'size': 1}]
        block_device_mapping = [{'mount_device': '/dev/sde',
                                 'device_path': 'fake_device'}]
        block_device_info = {
                'root_device_name': '/dev/sda',
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

        empty_block_device_info = {}

        self.assertEqual(
            driver.block_device_info_get_root(block_device_info), '/dev/sda')
        self.assertIsNone(
            driver.block_device_info_get_root(empty_block_device_info))
        self.assertIsNone(driver.block_device_info_get_root(None))

        self.assertEqual(
            driver.block_device_info_get_swap(block_device_info), swap)
        self.assertIsNone(driver.block_device_info_get_swap(
            empty_block_device_info)['device_name'])
        self.assertEqual(driver.block_device_info_get_swap(
            empty_block_device_info)['swap_size'], 0)
        self.assertIsNone(
            driver.block_device_info_get_swap({'swap': None})['device_name'])
        self.assertEqual(
            driver.block_device_info_get_swap({'swap': None})['swap_size'],
            0)
        self.assertIsNone(
            driver.block_device_info_get_swap(None)['device_name'])
        self.assertEqual(
            driver.block_device_info_get_swap(None)['swap_size'], 0)

        self.assertEqual(
            driver.block_device_info_get_ephemerals(block_device_info),
            ephemerals)
        self.assertEqual(
            driver.block_device_info_get_ephemerals(empty_block_device_info),
            [])
        self.assertEqual(
            driver.block_device_info_get_ephemerals(None),
            [])

    def test_swap_is_usable(self):
        self.assertFalse(driver.swap_is_usable(None))
        self.assertFalse(driver.swap_is_usable({'device_name': None}))
        self.assertFalse(driver.swap_is_usable({'device_name': '/dev/sdb',
                                                'swap_size': 0}))
        self.assertTrue(driver.swap_is_usable({'device_name': '/dev/sdb',
                                                'swap_size': 1}))


class FakeMount(object):
    def __init__(self, image, mount_dir, partition=None, device=None):
        self.image = image
        self.partition = partition
        self.mount_dir = mount_dir

        self.linked = self.mapped = self.mounted = False
        self.device = device

    def do_mount(self):
        self.linked = True
        self.mapped = True
        self.mounted = True
        self.device = '/dev/fake'
        return True

    def do_umount(self):
        self.linked = True
        self.mounted = False

    def do_teardown(self):
        self.linked = False
        self.mapped = False
        self.mounted = False
        self.device = None


class TestDiskImage(test.NoDBTestCase):
    def setUp(self):
        super(TestDiskImage, self).setUp()

    def mock_proc_mounts(self, mock_open):
        response = io.StringIO(unicode(PROC_MOUNTS_CONTENTS))
        mock_open.return_value = response

    @mock.patch('__builtin__.open')
    def test_mount(self, mock_open):
        self.mock_proc_mounts(mock_open)
        image = '/tmp/fake-image'
        mountdir = '/mnt/fake_rootfs'
        fakemount = FakeMount(image, mountdir, None)

        def fake_instance_for_format(imgfile, mountdir, partition, imgfmt):
            return fakemount

        self.stubs.Set(mount.Mount, 'instance_for_format',
                       staticmethod(fake_instance_for_format))
        diskimage = disk_api._DiskImage(image=image, mount_dir=mountdir)
        dev = diskimage.mount()
        self.assertEqual(diskimage._mounter, fakemount)
        self.assertEqual(dev, '/dev/fake')

    @mock.patch('__builtin__.open')
    def test_umount(self, mock_open):
        self.mock_proc_mounts(mock_open)

        image = '/tmp/fake-image'
        mountdir = '/mnt/fake_rootfs'
        fakemount = FakeMount(image, mountdir, None)

        def fake_instance_for_format(imgfile, mountdir, partition, imgfmt):
            return fakemount

        self.stubs.Set(mount.Mount, 'instance_for_format',
                       staticmethod(fake_instance_for_format))
        diskimage = disk_api._DiskImage(image=image, mount_dir=mountdir)
        dev = diskimage.mount()
        self.assertEqual(diskimage._mounter, fakemount)
        self.assertEqual(dev, '/dev/fake')
        diskimage.umount()
        self.assertIsNone(diskimage._mounter)

    @mock.patch('__builtin__.open')
    def test_teardown(self, mock_open):
        self.mock_proc_mounts(mock_open)

        image = '/tmp/fake-image'
        mountdir = '/mnt/fake_rootfs'
        fakemount = FakeMount(image, mountdir, None)

        def fake_instance_for_format(imgfile, mountdir, partition, imgfmt):
            return fakemount

        self.stubs.Set(mount.Mount, 'instance_for_format',
                       staticmethod(fake_instance_for_format))
        diskimage = disk_api._DiskImage(image=image, mount_dir=mountdir)
        dev = diskimage.mount()
        self.assertEqual(diskimage._mounter, fakemount)
        self.assertEqual(dev, '/dev/fake')
        diskimage.teardown()
        self.assertIsNone(diskimage._mounter)


class TestVirtDisk(test.NoDBTestCase):
    def setUp(self):
        super(TestVirtDisk, self).setUp()
        self.executes = []

        def fake_execute(*cmd, **kwargs):
            self.executes.append(cmd)
            return None, None

        self.stubs.Set(utils, 'execute', fake_execute)

    def test_lxc_setup_container(self):
        image = '/tmp/fake-image'
        container_dir = '/mnt/fake_rootfs/'

        def proc_mounts(self, mount_point):
            return None

        def fake_instance_for_format(imgfile, mountdir, partition, imgfmt):
            return FakeMount(imgfile, mountdir, partition)

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(disk_api._DiskImage, '_device_for_path', proc_mounts)
        self.stubs.Set(mount.Mount, 'instance_for_format',
                       staticmethod(fake_instance_for_format))

        self.assertEqual(disk_api.setup_container(image, container_dir),
                         '/dev/fake')

    def test_lxc_teardown_container(self):

        def proc_mounts(self, mount_point):
            mount_points = {
                '/mnt/loop/nopart': '/dev/loop0',
                '/mnt/loop/part': '/dev/mapper/loop0p1',
                '/mnt/nbd/nopart': '/dev/nbd15',
                '/mnt/nbd/part': '/dev/mapper/nbd15p1',
            }
            return mount_points[mount_point]

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(disk_api._DiskImage, '_device_for_path', proc_mounts)
        expected_commands = []

        disk_api.teardown_container('/mnt/loop/nopart')
        expected_commands += [
                              ('umount', '/dev/loop0'),
                              ('losetup', '--detach', '/dev/loop0'),
                             ]

        disk_api.teardown_container('/mnt/loop/part')
        expected_commands += [
                              ('umount', '/dev/mapper/loop0p1'),
                              ('kpartx', '-d', '/dev/loop0'),
                              ('losetup', '--detach', '/dev/loop0'),
                             ]

        disk_api.teardown_container('/mnt/nbd/nopart')
        expected_commands += [
                              ('blockdev', '--flushbufs', '/dev/nbd15'),
                              ('umount', '/dev/nbd15'),
                              ('qemu-nbd', '-d', '/dev/nbd15'),
                             ]

        disk_api.teardown_container('/mnt/nbd/part')
        expected_commands += [
                              ('blockdev', '--flushbufs', '/dev/nbd15'),
                              ('umount', '/dev/mapper/nbd15p1'),
                              ('kpartx', '-d', '/dev/nbd15'),
                              ('qemu-nbd', '-d', '/dev/nbd15'),
                             ]

        self.assertEqual(self.executes, expected_commands)

    def test_lxc_teardown_container_with_namespace_cleaned(self):

        def proc_mounts(self, mount_point):
            return None

        self.stubs.Set(os.path, 'exists', lambda _: True)
        self.stubs.Set(disk_api._DiskImage, '_device_for_path', proc_mounts)
        expected_commands = []

        disk_api.teardown_container('/mnt/loop/nopart', '/dev/loop0')
        expected_commands += [
                              ('losetup', '--detach', '/dev/loop0'),
                             ]

        disk_api.teardown_container('/mnt/loop/part', '/dev/loop0')
        expected_commands += [
                              ('losetup', '--detach', '/dev/loop0'),
                             ]

        disk_api.teardown_container('/mnt/nbd/nopart', '/dev/nbd15')
        expected_commands += [
                              ('qemu-nbd', '-d', '/dev/nbd15'),
                             ]

        disk_api.teardown_container('/mnt/nbd/part', '/dev/nbd15')
        expected_commands += [
                              ('qemu-nbd', '-d', '/dev/nbd15'),
                             ]

        self.assertEqual(self.executes, expected_commands)
