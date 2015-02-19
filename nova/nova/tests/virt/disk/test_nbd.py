# Copyright 2012 Michael Still and Canonical Inc
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


import os
import tempfile
import time

import eventlet
import fixtures

from nova import test
from nova.virt.disk.mount import nbd

ORIG_EXISTS = os.path.exists
ORIG_LISTDIR = os.listdir


def _fake_exists_no_users(path):
    if path.startswith('/sys/block/nbd'):
        if path.endswith('pid'):
            return False
        return True
    return ORIG_EXISTS(path)


def _fake_listdir_nbd_devices(path):
    if path.startswith('/sys/block'):
        return ['nbd0', 'nbd1']
    return ORIG_LISTDIR(path)


def _fake_exists_all_used(path):
    if path.startswith('/sys/block/nbd'):
        return True
    return ORIG_EXISTS(path)


def _fake_detect_nbd_devices_none(self):
    return []


def _fake_detect_nbd_devices(self):
    return ['nbd0', 'nbd1']


def _fake_noop(*args, **kwargs):
    return


class NbdTestCase(test.NoDBTestCase):
    def setUp(self):
        super(NbdTestCase, self).setUp()
        self.stubs.Set(nbd.NbdMount, '_detect_nbd_devices',
                       _fake_detect_nbd_devices)
        self.useFixture(fixtures.MonkeyPatch('os.listdir',
                                             _fake_listdir_nbd_devices))

    def test_nbd_no_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        self.stubs.Set(nbd.NbdMount, '_detect_nbd_devices',
                       _fake_detect_nbd_devices_none)
        n = nbd.NbdMount(None, tempdir)
        self.assertIsNone(n._allocate_nbd())

    def test_nbd_no_free_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_all_used))
        self.assertIsNone(n._allocate_nbd())

    def test_nbd_not_loaded(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                return False
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # This should fail, as we don't have the module "loaded"
        # TODO(mikal): work out how to force english as the gettext language
        # so that the error check always passes
        self.assertIsNone(n._allocate_nbd())
        self.assertEqual('nbd unavailable: module not loaded', n.error)

    def test_nbd_allocation(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))

        # Allocate a nbd device
        self.assertEqual('/dev/nbd0', n._allocate_nbd())

    def test_nbd_allocation_one_in_use(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))

        # Fake out os.path.exists
        def fake_exists(path):
            if path.startswith('/sys/block/nbd'):
                if path == '/sys/block/nbd0/pid':
                    return True
                if path.endswith('pid'):
                    return False
                return True
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists', fake_exists))

        # Allocate a nbd device, should not be the in use one
        # TODO(mikal): Note that there is a leak here, as the in use nbd device
        # is removed from the list, but not returned so it will never be
        # re-added. I will fix this in a later patch.
        self.assertEqual('/dev/nbd1', n._allocate_nbd())

    def test_inner_get_dev_no_devices(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        self.stubs.Set(nbd.NbdMount, '_detect_nbd_devices',
                       _fake_detect_nbd_devices_none)
        n = nbd.NbdMount(None, tempdir)
        self.assertFalse(n._inner_get_dev())

    def test_inner_get_dev_qemu_fails(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # We have a trycmd that always fails
        def fake_trycmd(*args, **kwargs):
            return '', 'broken'
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        # Error logged, no device consumed
        self.assertFalse(n._inner_get_dev())
        self.assertTrue(n.error.startswith('qemu-nbd error'))

    def test_inner_get_dev_qemu_timeout(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             _fake_exists_no_users))

        # We have a trycmd that always passed
        def fake_trycmd(*args, **kwargs):
            return '', ''
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))
        self.useFixture(fixtures.MonkeyPatch('time.sleep', _fake_noop))

        # Error logged, no device consumed
        self.assertFalse(n._inner_get_dev())
        self.assertTrue(n.error.endswith('did not show up'))

    def fake_exists_one(self, path):
        # We need the pid file for the device which is allocated to exist, but
        # only once it is allocated to us
        if path.startswith('/sys/block/nbd'):
            if path == '/sys/block/nbd1/pid':
                return False
            if path.endswith('pid'):
                return False
            return True
        return ORIG_EXISTS(path)

    def fake_trycmd_creates_pid(self, *args, **kwargs):
        def fake_exists_two(path):
            if path.startswith('/sys/block/nbd'):
                if path == '/sys/block/nbd0/pid':
                    return True
                if path.endswith('pid'):
                    return False
                return True
            return ORIG_EXISTS(path)
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                            fake_exists_two))
        return '', ''

    def test_inner_get_dev_works(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             self.fake_exists_one))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd',
                                             self.fake_trycmd_creates_pid))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute', _fake_noop))

        # No error logged, device consumed
        self.assertTrue(n._inner_get_dev())
        self.assertTrue(n.linked)
        self.assertEqual('', n.error)
        self.assertEqual('/dev/nbd0', n.device)

        # Free
        n.unget_dev()
        self.assertFalse(n.linked)
        self.assertEqual('', n.error)
        self.assertIsNone(n.device)

    def test_unget_dev_simple(self):
        # This test is just checking we don't get an exception when we unget
        # something we don't have
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute', _fake_noop))
        n.unget_dev()

    def test_get_dev(self):
        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             self.fake_exists_one))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd',
                                             self.fake_trycmd_creates_pid))

        # No error logged, device consumed
        self.assertTrue(n.get_dev())
        self.assertTrue(n.linked)
        self.assertEqual('', n.error)
        self.assertEqual('/dev/nbd0', n.device)

        # Free
        n.unget_dev()
        self.assertFalse(n.linked)
        self.assertEqual('', n.error)
        self.assertIsNone(n.device)

    def test_get_dev_timeout(self):
        # Always fail to get a device
        def fake_get_dev_fails(self):
            return False
        self.stubs.Set(nbd.NbdMount, '_inner_get_dev', fake_get_dev_fails)

        tempdir = self.useFixture(fixtures.TempDir()).path
        n = nbd.NbdMount(None, tempdir)
        self.useFixture(fixtures.MonkeyPatch('random.shuffle', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('time.sleep', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.execute', _fake_noop))
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             self.fake_exists_one))
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd',
                                             self.fake_trycmd_creates_pid))
        self.useFixture(fixtures.MonkeyPatch(('nova.virt.disk.mount.api.'
                                              'MAX_DEVICE_WAIT'), -10))

        # No error logged, device consumed
        self.assertFalse(n.get_dev())

    def test_do_mount_need_to_specify_fs_type(self):
        # NOTE(mikal): Bug 1094373 saw a regression where we failed to
        # communicate a failed mount properly.
        def fake_trycmd(*args, **kwargs):
            return '', 'broken'
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd', fake_trycmd))

        imgfile = tempfile.NamedTemporaryFile()
        self.addCleanup(imgfile.close)
        tempdir = self.useFixture(fixtures.TempDir()).path
        mount = nbd.NbdMount(imgfile.name, tempdir)

        def fake_returns_true(*args, **kwargs):
            return True
        mount.get_dev = fake_returns_true
        mount.map_dev = fake_returns_true

        self.assertFalse(mount.do_mount())

    def test_device_creation_race(self):
        # Make sure that even if two threads create instances at the same time
        # they cannot choose the same nbd number (see bug 1207422)

        tempdir = self.useFixture(fixtures.TempDir()).path
        free_devices = _fake_detect_nbd_devices(None)[:]
        chosen_devices = []

        def fake_find_unused(self):
            return os.path.join('/dev', free_devices[-1])

        def delay_and_remove_device(*args, **kwargs):
            # Ensure that context switch happens before the device is marked
            # as used. This will cause a failure without nbd-allocation-lock
            # in place.
            time.sleep(0.1)

            # We always choose the top device in find_unused - remove it now.
            free_devices.pop()

            return '', ''

        def pid_exists(pidfile):
            return pidfile not in [os.path.join('/sys/block', dev, 'pid')
                                   for dev in free_devices]

        self.stubs.Set(nbd.NbdMount, '_allocate_nbd', fake_find_unused)
        self.useFixture(fixtures.MonkeyPatch('nova.utils.trycmd',
                                             delay_and_remove_device))
        self.useFixture(fixtures.MonkeyPatch('os.path.exists',
                                             pid_exists))

        def get_a_device():
            n = nbd.NbdMount(None, tempdir)
            n.get_dev()
            chosen_devices.append(n.device)

        thread1 = eventlet.spawn(get_a_device)
        thread2 = eventlet.spawn(get_a_device)
        thread1.wait()
        thread2.wait()

        self.assertEqual(2, len(chosen_devices))
        self.assertNotEqual(chosen_devices[0], chosen_devices[1])
