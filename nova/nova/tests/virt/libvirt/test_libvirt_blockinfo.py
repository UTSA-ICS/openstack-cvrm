#    Copyright 2010 OpenStack Foundation
#    Copyright 2012 University Of Minho
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

import copy

import mock

from nova import block_device
from nova.compute import flavors
from nova import context
from nova import db
from nova import exception
from nova.objects import block_device as block_device_obj
from nova import test
from nova.tests import fake_block_device
import nova.tests.image.fake
from nova.virt import block_device as driver_block_device
from nova.virt.libvirt import blockinfo


class LibvirtBlockInfoTest(test.TestCase):

    def setUp(self):
        super(LibvirtBlockInfoTest, self).setUp()

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.get_admin_context()
        flavor = db.flavor_get(self.context, 2)
        sys_meta = flavors.save_flavor_info({}, flavor)
        nova.tests.image.fake.stub_out_image_service(self.stubs)
        self.test_instance = {
                'uuid': '32dfcb37-5af1-552b-357c-be8c3aa38310',
                'memory_kb': '1024000',
                'basepath': '/some/path',
                'bridge_name': 'br100',
                'vcpus': 2,
                'project_id': 'fake',
                'bridge': 'br101',
                'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'root_gb': 10,
                'ephemeral_gb': 20,
                'instance_type_id': 2,  # m1.tiny
                'system_metadata': sys_meta}

    def test_volume_in_mapping(self):
        swap = {'device_name': '/dev/sdb',
                'swap_size': 1}
        ephemerals = [{'device_type': 'disk', 'guest_format': 'ext3',
                       'device_name': '/dev/sdc1', 'size': 10},
                      {'disk_bus': 'ide', 'guest_format': None,
                       'device_name': '/dev/sdd', 'size': 10}]
        block_device_mapping = [{'mount_device': '/dev/sde',
                                 'device_path': 'fake_device'},
                                {'mount_device': '/dev/sdf',
                                 'device_path': 'fake_device'}]
        block_device_info = {
                'root_device_name': '/dev/sda',
                'swap': swap,
                'ephemerals': ephemerals,
                'block_device_mapping': block_device_mapping}

        def _assert_volume_in_mapping(device_name, true_or_false):
            self.assertEqual(
                true_or_false,
                block_device.volume_in_mapping(device_name,
                                               block_device_info))

        _assert_volume_in_mapping('sda', False)
        _assert_volume_in_mapping('sdb', True)
        _assert_volume_in_mapping('sdc1', True)
        _assert_volume_in_mapping('sdd', True)
        _assert_volume_in_mapping('sde', True)
        _assert_volume_in_mapping('sdf', True)
        _assert_volume_in_mapping('sdg', False)
        _assert_volume_in_mapping('sdh1', False)

    def test_find_disk_dev(self):
        mapping = {
            "disk.local": {
                'dev': 'sda',
                'bus': 'scsi',
                'type': 'disk',
                },
            "disk.swap": {
                'dev': 'sdc',
                'bus': 'scsi',
                'type': 'disk',
                },
            }

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'scsi')
        self.assertEqual('sdb', dev)

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'scsi',
                                                   last_device=True)
        self.assertEqual('sdz', dev)

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'virtio')
        self.assertEqual('vda', dev)

        dev = blockinfo.find_disk_dev_for_disk_bus(mapping, 'fdc')
        self.assertEqual('fda', dev)

    def test_get_next_disk_dev(self):
        mapping = {}
        mapping['disk.local'] = blockinfo.get_next_disk_info(mapping,
                                                             'virtio')
        self.assertEqual({'dev': 'vda', 'bus': 'virtio', 'type': 'disk'},
                         mapping['disk.local'])

        mapping['disk.swap'] = blockinfo.get_next_disk_info(mapping,
                                                            'virtio')
        self.assertEqual({'dev': 'vdb', 'bus': 'virtio', 'type': 'disk'},
                         mapping['disk.swap'])

        mapping['disk.config'] = blockinfo.get_next_disk_info(mapping,
                                                              'ide',
                                                              'cdrom',
                                                              True)
        self.assertEqual({'dev': 'hdd', 'bus': 'ide', 'type': 'cdrom'},
                         mapping['disk.config'])

    def test_get_next_disk_dev_boot_index(self):
        info = blockinfo.get_next_disk_info({}, 'virtio', boot_index=-1)
        self.assertEqual({'dev': 'vda', 'bus': 'virtio', 'type': 'disk'}, info)

        info = blockinfo.get_next_disk_info({}, 'virtio', boot_index=2)
        self.assertEqual({'dev': 'vda', 'bus': 'virtio',
                          'type': 'disk', 'boot_index': '2'},
                         info)

    def test_get_disk_mapping_simple(self):
        # The simplest possible disk mapping setup, all defaults

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'}
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_rootdev(self):
        # A simple disk mapping setup, but with custom root device name

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)
        block_device_info = {
            'root_device_name': '/dev/sda'
            }

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'scsi', 'dev': 'sda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'root': {'bus': 'scsi', 'dev': 'sda',
                     'type': 'disk', 'boot_index': '1'}
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_rescue(self):
        # A simple disk mapping setup, but in rescue mode

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             rescue=True)

        expect = {
            'disk.rescue': {'bus': 'virtio', 'dev': 'vda',
                            'type': 'disk', 'boot_index': '1'},
            'disk': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_lxc(self):
        # A simple disk mapping setup, but for lxc

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("lxc", instance_ref,
                                             "lxc", "lxc",
                                             None)
        expect = {
            'disk': {'bus': 'lxc', 'dev': None,
                     'type': 'disk', 'boot_index': '1'},
            'root': {'bus': 'lxc', 'dev': None,
                     'type': 'disk', 'boot_index': '1'},
        }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_iso(self):
        # A simple disk mapping setup, but with a ISO for root device

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)
        image_meta = {'disk_format': 'iso'}

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             None,
                                             image_meta)

        expect = {
            'disk': {'bus': 'ide', 'dev': 'hda',
                     'type': 'cdrom', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vda', 'type': 'disk'},
            'root': {'bus': 'ide', 'dev': 'hda',
                     'type': 'cdrom', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_swap(self):
        # A simple disk mapping setup, but with a swap device added

        user_context = context.RequestContext(self.user_id, self.project_id)
        self.test_instance['system_metadata']['instance_type_swap'] = 5
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdc', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_simple_configdrive(self):
        # A simple disk mapping setup, but with configdrive added

        self.flags(force_config_drive=True)

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config': {'bus': 'ide', 'dev': 'hdd', 'type': 'cdrom'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'}
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_cdrom_configdrive(self):
        # A simple disk mapping setup, with configdrive added as cdrom

        self.flags(force_config_drive=True)
        self.flags(config_drive_format='iso9660')

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config': {'bus': 'ide', 'dev': 'hdd', 'type': 'cdrom'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'}
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_disk_configdrive(self):
        # A simple disk mapping setup, with configdrive added as disk

        self.flags(force_config_drive=True)
        self.flags(config_drive_format='vfat')

        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide")

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'disk.config': {'bus': 'virtio', 'dev': 'vdz', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_ephemeral(self):
        # A disk mapping with ephemeral devices
        user_context = context.RequestContext(self.user_id, self.project_id)
        self.test_instance['system_metadata']['instance_type_swap'] = 5
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'ephemerals': [
                {'device_type': 'disk', 'guest_format': 'ext3',
                 'device_name': '/dev/vdb', 'size': 10},
                {'disk_bus': 'ide', 'guest_format': None,
                 'device_name': '/dev/vdc', 'size': 10},
                {'device_type': 'floppy',
                 'device_name': '/dev/vdd', 'size': 10},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.eph0': {'bus': 'virtio', 'dev': 'vdb',
                          'type': 'disk', 'format': 'ext3'},
            'disk.eph1': {'bus': 'ide', 'dev': 'vdc', 'type': 'disk'},
            'disk.eph2': {'bus': 'virtio', 'dev': 'vdd', 'type': 'floppy'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vde', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_custom_swap(self):
        # A disk mapping with a swap device at position vdb. This
        # should cause disk.local to be removed
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'swap': {'device_name': '/dev/vdb',
                     'swap_size': 10},
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_blockdev_root(self):
        # A disk mapping with a blockdev replacing the default root
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'boot_index': 0,
                 'device_type': 'disk',
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '1'},
            'disk.local': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_blockdev_eph(self):
        # A disk mapping with a blockdev replacing the ephemeral device
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vdb",
                 'boot_index': -1,
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_blockdev_many(self):
        # A disk mapping with a blockdev replacing all devices
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'boot_index': 0,
                 'disk_bus': 'scsi',
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdb",
                 'boot_index': -1,
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdc",
                 'boot_index': -1,
                 'device_type': 'cdrom',
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            '/dev/vda': {'bus': 'scsi', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '1'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb', 'type': 'disk'},
            '/dev/vdc': {'bus': 'virtio', 'dev': 'vdc', 'type': 'cdrom'},
            'root': {'bus': 'scsi', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_complex(self):
        # The strangest possible disk mapping setup
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'root_device_name': '/dev/vdf',
            'swap': {'device_name': '/dev/vdy',
                     'swap_size': 10},
            'ephemerals': [
                {'device_type': 'disk', 'guest_format': 'ext3',
                 'device_name': '/dev/vdb', 'size': 10},
                {'disk_bus': 'ide', 'guest_format': None,
                 'device_name': '/dev/vdc', 'size': 10},
                ],
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': "/dev/vda",
                 'boot_index': 1,
                 'delete_on_termination': True},
                ]
            }
        mapping = blockinfo.get_disk_mapping("kvm", instance_ref,
                                             "virtio", "ide",
                                             block_device_info)

        expect = {
            'disk': {'bus': 'virtio', 'dev': 'vdf',
                     'type': 'disk', 'boot_index': '1'},
            '/dev/vda': {'bus': 'virtio', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '2'},
            'disk.eph0': {'bus': 'virtio', 'dev': 'vdb',
                          'type': 'disk', 'format': 'ext3'},
            'disk.eph1': {'bus': 'ide', 'dev': 'vdc', 'type': 'disk'},
            'disk.swap': {'bus': 'virtio', 'dev': 'vdy', 'type': 'disk'},
            'root': {'bus': 'virtio', 'dev': 'vdf',
                     'type': 'disk', 'boot_index': '1'},
            }
        self.assertEqual(expect, mapping)

    def test_get_disk_mapping_updates_original(self):
        user_context = context.RequestContext(self.user_id, self.project_id)
        instance_ref = db.instance_create(user_context, self.test_instance)

        block_device_info = {
            'root_device_name': '/dev/vda',
            'swap': {'device_name': '/dev/vdb',
                     'device_type': 'really_lame_type',
                     'swap_size': 10},
            'ephemerals': [{'disk_bus': 'no_such_bus',
                            'device_type': 'yeah_right',
                            'device_name': '/dev/vdc', 'size': 10}],
            'block_device_mapping': [
                {'connection_info': "fake",
                 'mount_device': None,
                 'device_type': 'lawnmower',
                 'delete_on_termination': True}]
            }
        expected_swap = {'device_name': '/dev/vdb', 'disk_bus': 'virtio',
                         'device_type': 'disk', 'swap_size': 10}
        expected_ephemeral = {'disk_bus': 'virtio',
                              'device_type': 'disk',
                              'device_name': '/dev/vdc', 'size': 10}
        expected_bdm = {'connection_info': "fake",
                        'mount_device': '/dev/vdd',
                        'device_type': 'disk',
                        'disk_bus': 'virtio',
                        'delete_on_termination': True}

        blockinfo.get_disk_mapping("kvm", instance_ref,
                                   "virtio", "ide", block_device_info)

        self.assertEqual(expected_swap, block_device_info['swap'])
        self.assertEqual(expected_ephemeral,
                         block_device_info['ephemerals'][0])
        self.assertEqual(expected_bdm,
                         block_device_info['block_device_mapping'][0])

    def test_get_disk_bus(self):
        expected = (
                ('x86_64', 'disk', 'virtio'),
                ('x86_64', 'cdrom', 'ide'),
                ('x86_64', 'floppy', 'fdc'),
                ('ppc', 'disk', 'virtio'),
                ('ppc', 'cdrom', 'scsi'),
                ('ppc64', 'disk', 'virtio'),
                ('ppc64', 'cdrom', 'scsi')
                )
        for arch, dev, res in expected:
            with mock.patch.object(blockinfo.libvirt_utils,
                                   'get_arch',
                                   return_value=arch):
                bus = blockinfo.get_disk_bus_for_device_type('kvm',
                            device_type=dev)
                self.assertEqual(res, bus)

        expected = (
                ('scsi', None, 'disk', 'scsi'),
                (None, 'scsi', 'cdrom', 'scsi'),
                ('usb', None, 'disk', 'usb')
                )
        for dbus, cbus, dev, res in expected:
            image_meta = {'properties': {'hw_disk_bus': dbus,
                                         'hw_cdrom_bus': cbus}}
            bus = blockinfo.get_disk_bus_for_device_type('kvm',
                                                     image_meta,
                                                     device_type=dev)
            self.assertEqual(res, bus)

        image_meta = {'properties': {'hw_disk_bus': 'xen'}}
        self.assertRaises(exception.UnsupportedHardware,
                          blockinfo.get_disk_bus_for_device_type,
                          'kvm',
                          image_meta)

    def test_success_get_disk_bus_for_disk_dev(self):
        expected = (
                ('ide', ("kvm", "hda")),
                ('scsi', ("kvm", "sdf")),
                ('virtio', ("kvm", "vds")),
                ('fdc', ("kvm", "fdc")),
                ('uml', ("kvm", "ubd")),
                ('xen', ("xen", "sdf")),
                ('xen', ("xen", "xvdb"))
                )
        for res, args in expected:
            self.assertEqual(res, blockinfo.get_disk_bus_for_disk_dev(*args))

    def test_fail_get_disk_bus_for_disk_dev(self):
        self.assertRaises(exception.NovaException,
                blockinfo.get_disk_bus_for_disk_dev, 'inv', 'val')

    def test_get_config_drive_type_default(self):
        config_drive_type = blockinfo.get_config_drive_type()
        self.assertEqual('cdrom', config_drive_type)

    def test_get_config_drive_type_cdrom(self):
        self.flags(config_drive_format='iso9660')
        config_drive_type = blockinfo.get_config_drive_type()
        self.assertEqual('cdrom', config_drive_type)

    def test_get_config_drive_type_disk(self):
        self.flags(config_drive_format='vfat')
        config_drive_type = blockinfo.get_config_drive_type()
        self.assertEqual('disk', config_drive_type)

    def test_get_config_drive_type_improper_value(self):
        self.flags(config_drive_format='test')
        self.assertRaises(exception.ConfigDriveUnknownFormat,
                          blockinfo.get_config_drive_type)

    def test_get_info_from_bdm(self):
        bdms = [{'device_name': '/dev/vds', 'device_type': 'disk',
                 'disk_bus': 'usb', 'swap_size': 4},
                {'device_type': 'disk', 'guest_format': 'ext3',
                 'device_name': '/dev/vdb', 'size': 2},
                {'disk_bus': 'ide', 'guest_format': None,
                 'device_name': '/dev/vdc', 'size': 3},
                {'connection_info': "fake",
                 'mount_device': "/dev/sdr",
                 'disk_bus': 'lame_bus',
                 'device_type': 'cdrom',
                 'boot_index': 0,
                 'delete_on_termination': True},
                {'connection_info': "fake",
                 'mount_device': "/dev/vdo",
                 'disk_bus': 'scsi',
                 'boot_index': 1,
                 'device_type': 'lame_type',
                 'delete_on_termination': True}]
        expected = [{'dev': 'vds', 'type': 'disk', 'bus': 'usb'},
                    {'dev': 'vdb', 'type': 'disk',
                     'bus': 'virtio', 'format': 'ext3'},
                    {'dev': 'vdc', 'type': 'disk', 'bus': 'ide'},
                    {'dev': 'sdr', 'type': 'cdrom',
                     'bus': 'scsi', 'boot_index': '1'},
                    {'dev': 'vdo', 'type': 'disk',
                     'bus': 'scsi', 'boot_index': '2'}]

        for bdm, expected in zip(bdms, expected):
            self.assertEqual(expected,
                             blockinfo.get_info_from_bdm('kvm', bdm, {}))

        # Test that passed bus and type are considered
        bdm = {'device_name': '/dev/vda'}
        expected = {'dev': 'vda', 'type': 'disk', 'bus': 'ide'}
        self.assertEqual(
            expected, blockinfo.get_info_from_bdm('kvm', bdm, {},
                                                  disk_bus='ide',
                                                  dev_type='disk'))

        # Test that lame bus values are defaulted properly
        bdm = {'disk_bus': 'lame_bus', 'device_type': 'cdrom'}
        with mock.patch.object(blockinfo,
                               'get_disk_bus_for_device_type',
                               return_value='ide') as get_bus:
            blockinfo.get_info_from_bdm('kvm', bdm, {})
            get_bus.assert_called_once_with('kvm', None, 'cdrom')

        # Test that missing device is defaulted as expected
        bdm = {'disk_bus': 'ide', 'device_type': 'cdrom'}
        expected = {'dev': 'vdd', 'type': 'cdrom', 'bus': 'ide'}
        mapping = {'root': {'dev': 'vda'}}
        with mock.patch.object(blockinfo,
                               'find_disk_dev_for_disk_bus',
                               return_value='vdd') as find_dev:
            got = blockinfo.get_info_from_bdm(
                'kvm', bdm, mapping, assigned_devices=['vdb', 'vdc'])
            find_dev.assert_called_once_with(
                {'root': {'dev': 'vda'},
                 'vdb': {'dev': 'vdb'},
                 'vdc': {'dev': 'vdc'}}, 'ide')
            self.assertEqual(expected, got)

    def test_get_device_name(self):
        bdm_obj = block_device_obj.BlockDeviceMapping(self.context,
            **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 3, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/vda',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'volume_id': 'fake-volume-id-1',
                 'boot_index': 0}))
        self.assertEqual('/dev/vda', blockinfo.get_device_name(bdm_obj))

        driver_bdm = driver_block_device.DriverVolumeBlockDevice(bdm_obj)
        self.assertEqual('/dev/vda', blockinfo.get_device_name(driver_bdm))

        bdm_obj.device_name = None
        self.assertEqual(None, blockinfo.get_device_name(bdm_obj))

        driver_bdm = driver_block_device.DriverVolumeBlockDevice(bdm_obj)
        self.assertEqual(None, blockinfo.get_device_name(driver_bdm))

    @mock.patch('nova.virt.libvirt.blockinfo.find_disk_dev_for_disk_bus',
                return_value='vda')
    @mock.patch('nova.virt.libvirt.blockinfo.get_disk_bus_for_disk_dev',
                return_value='virtio')
    def test_get_root_info_no_bdm(self, mock_get_bus, mock_find_dev):
        blockinfo.get_root_info('kvm', None, None, 'virtio', 'ide')
        mock_find_dev.assert_called_once_with({}, 'virtio')

        blockinfo.get_root_info('kvm', None, None, 'virtio', 'ide',
                                 root_device_name='/dev/vda')
        mock_get_bus.assert_called_once_with('kvm', '/dev/vda')

    @mock.patch('nova.virt.libvirt.blockinfo.get_info_from_bdm')
    def test_get_root_info_bdm(self, mock_get_info):
        root_bdm = {'mount_device': '/dev/vda',
                    'disk_bus': 'scsi',
                    'device_type': 'disk'}
        # No root_device_name
        blockinfo.get_root_info('kvm', None, root_bdm, 'virtio', 'ide')
        mock_get_info.assert_called_once_with('kvm', root_bdm, {}, 'virtio')
        mock_get_info.reset_mock()
        # Both device names
        blockinfo.get_root_info('kvm', None, root_bdm, 'virtio', 'ide',
                                root_device_name='sda')
        mock_get_info.assert_called_once_with('kvm', root_bdm, {}, 'virtio')
        mock_get_info.reset_mock()
        # Missing device names
        del root_bdm['mount_device']
        blockinfo.get_root_info('kvm', None, root_bdm, 'virtio', 'ide',
                                root_device_name='sda')
        mock_get_info.assert_called_once_with('kvm',
                                              {'device_name': 'sda',
                                               'disk_bus': 'scsi',
                                               'device_type': 'disk'},
                                              {}, 'virtio')

    def test_get_boot_order_simple(self):
        disk_info = {
            'disk_bus': 'virtio',
            'cdrom_bus': 'ide',
            'mapping': {
            'disk': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            'root': {'bus': 'virtio', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        }
        expected_order = ['hd']
        self.assertEqual(expected_order, blockinfo.get_boot_order(disk_info))

    def test_get_boot_order_complex(self):
        disk_info = {
            'disk_bus': 'virtio',
            'cdrom_bus': 'ide',
            'mapping': {
                'disk': {'bus': 'virtio', 'dev': 'vdf',
                         'type': 'disk', 'boot_index': '1'},
                '/dev/hda': {'bus': 'ide', 'dev': 'hda',
                             'type': 'cdrom', 'boot_index': '3'},
                '/dev/fda': {'bus': 'fdc', 'dev': 'fda',
                             'type': 'floppy', 'boot_index': '2'},
                'disk.eph0': {'bus': 'virtio', 'dev': 'vdb',
                              'type': 'disk', 'format': 'ext3'},
                'disk.eph1': {'bus': 'ide', 'dev': 'vdc', 'type': 'disk'},
                'disk.swap': {'bus': 'virtio', 'dev': 'vdy', 'type': 'disk'},
                'root': {'bus': 'virtio', 'dev': 'vdf',
                         'type': 'disk', 'boot_index': '1'},
            }
        }
        expected_order = ['hd', 'fd', 'cdrom']
        self.assertEqual(expected_order, blockinfo.get_boot_order(disk_info))

    def test_get_boot_order_overlapping(self):
        disk_info = {
            'disk_bus': 'virtio',
            'cdrom_bus': 'ide',
            'mapping': {
            '/dev/vda': {'bus': 'scsi', 'dev': 'vda',
                         'type': 'disk', 'boot_index': '1'},
            '/dev/vdb': {'bus': 'virtio', 'dev': 'vdb',
                         'type': 'disk', 'boot_index': '2'},
            '/dev/vdc': {'bus': 'virtio', 'dev': 'vdc',
                         'type': 'cdrom', 'boot_index': '3'},
            'root': {'bus': 'scsi', 'dev': 'vda',
                     'type': 'disk', 'boot_index': '1'},
            }
        }
        expected_order = ['hd', 'cdrom']
        self.assertEqual(expected_order, blockinfo.get_boot_order(disk_info))


class DefaultDeviceNamesTestCase(test.TestCase):
    def setUp(self):
        super(DefaultDeviceNamesTestCase, self).setUp()
        self.context = context.get_admin_context()
        self.instance = {
                'uuid': '32dfcb37-5af1-552b-357c-be8c3aa38310',
                'memory_kb': '1024000',
                'basepath': '/some/path',
                'bridge_name': 'br100',
                'vcpus': 2,
                'project_id': 'fake',
                'bridge': 'br101',
                'image_ref': '155d900f-4e14-4e4c-a73d-069cbf4541e6',
                'root_gb': 10,
                'ephemeral_gb': 20,
                'instance_type_id': 2}
        self.root_device_name = '/dev/vda'
        self.virt_type = 'kvm'
        self.flavor = {'swap': 4}
        self.patchers = []
        self.patchers.append(mock.patch('nova.compute.flavors.extract_flavor',
                            return_value=self.flavor))
        self.patchers.append(mock.patch(
                'nova.objects.block_device.BlockDeviceMapping.save'))
        for patcher in self.patchers:
            patcher.start()

        self.ephemerals = [block_device_obj.BlockDeviceMapping(
            self.context, **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 1, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/vdb',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'delete_on_termination': True,
                 'guest_format': None,
                 'volume_size': 1,
                 'boot_index': -1}))]

        self.swap = [block_device_obj.BlockDeviceMapping(
            self.context, **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 2, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/vdc',
                 'source_type': 'blank',
                 'destination_type': 'local',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'delete_on_termination': True,
                 'guest_format': 'swap',
                 'volume_size': 1,
                 'boot_index': -1}))]

        self.block_device_mapping = [
            block_device_obj.BlockDeviceMapping(self.context,
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 3, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/vda',
                 'source_type': 'volume',
                 'destination_type': 'volume',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'volume_id': 'fake-volume-id-1',
                 'boot_index': 0})),
            block_device_obj.BlockDeviceMapping(self.context,
                **fake_block_device.FakeDbBlockDeviceDict(
                {'id': 4, 'instance_uuid': 'fake-instance',
                 'device_name': '/dev/vdd',
                 'source_type': 'snapshot',
                 'device_type': 'disk',
                 'disk_bus': 'virtio',
                 'destination_type': 'volume',
                 'snapshot_id': 'fake-snapshot-id-1',
                 'boot_index': -1}))]

    def tearDown(self):
        super(DefaultDeviceNamesTestCase, self).tearDown()
        for patcher in self.patchers:
            patcher.stop()

    def _test_default_device_names(self, *block_device_lists):
        blockinfo.default_device_names(self.virt_type,
                                       self.context,
                                       self.instance,
                                       self.root_device_name,
                                       *block_device_lists)

    def test_only_block_device_mapping(self):
        # Test no-op
        original_bdm = copy.deepcopy(self.block_device_mapping)
        self._test_default_device_names([], [], self.block_device_mapping)
        for original, defaulted in zip(
                original_bdm, self.block_device_mapping):
            self.assertEqual(original.device_name, defaulted.device_name)

        # Asser it defaults the missing one as expected
        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names([], [], self.block_device_mapping)
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])

    def test_with_ephemerals(self):
        # Test ephemeral gets assigned
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual('/dev/vdb', self.ephemerals[0]['device_name'])

        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])

    def test_with_swap(self):
        # Test swap only
        self.swap[0]['device_name'] = None
        self._test_default_device_names([], self.swap, [])
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])

        # Test swap and block_device_mapping
        self.swap[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names([], self.swap,
                                        self.block_device_mapping)
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])

    def test_all_together(self):
        # Test swap missing
        self.swap[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])

        # Test swap and eph missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual('/dev/vdb', self.ephemerals[0]['device_name'])
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])

        # Test all missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual('/dev/vdb', self.ephemerals[0]['device_name'])
        self.assertEqual('/dev/vdc', self.swap[0]['device_name'])
        self.assertEqual('/dev/vdd',
                         self.block_device_mapping[1]['device_name'])
