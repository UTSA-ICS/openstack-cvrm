# Copyright 2011 OpenStack Foundation
# All Rights Reserved.
# Copyright 2013 Red Hat, Inc.
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

"""Tests For miscellaneous util methods used with compute."""

import copy
import string

import mock
from oslo.config import cfg

from nova.compute import flavors
from nova.compute import power_state
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova import context
from nova import db
from nova import exception
from nova.image import glance
from nova.network import api as network_api
from nova.objects import block_device as block_device_obj
from nova.objects import instance as instance_obj
from nova.openstack.common import importutils
from nova.openstack.common import jsonutils
from nova import rpc
from nova import test
from nova.tests import fake_block_device
from nova.tests import fake_instance
from nova.tests import fake_instance_actions
from nova.tests import fake_network
from nova.tests import fake_notifier
import nova.tests.image.fake
from nova.tests import matchers
from nova.virt import driver

CONF = cfg.CONF
CONF.import_opt('compute_manager', 'nova.service')
CONF.import_opt('compute_driver', 'nova.virt.driver')


class ComputeValidateDeviceTestCase(test.TestCase):
    def setUp(self):
        super(ComputeValidateDeviceTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        # check if test name includes "xen"
        if 'xen' in self.id():
            self.flags(compute_driver='xenapi.XenAPIDriver')
            self.instance = {
                    'uuid': 'fake',
                    'root_device_name': None,
                    'instance_type_id': 'fake',
            }
        else:
            self.instance = {
                    'uuid': 'fake',
                    'root_device_name': '/dev/vda',
                    'default_ephemeral_device': '/dev/vdb',
                    'instance_type_id': 'fake',
            }
        self.data = []

        self.stubs.Set(db, 'block_device_mapping_get_all_by_instance',
                       lambda context, instance, use_slave=False: self.data)

    def _update_flavor(self, flavor_info):
        self.flavor = {
            'id': 1,
            'name': 'foo',
            'memory_mb': 128,
            'vcpus': 1,
            'root_gb': 10,
            'ephemeral_gb': 10,
            'flavorid': 1,
            'swap': 0,
            'rxtx_factor': 1.0,
            'vcpu_weight': 1,
            }
        self.flavor.update(flavor_info)
        self.instance['system_metadata'] = [{'key': 'instance_type_%s' % key,
                                             'value': value}
                                            for key, value in
                                            self.flavor.items()]

    def _validate_device(self, device=None):
        bdms = block_device_obj.BlockDeviceMappingList.get_by_instance_uuid(
                self.context, self.instance['uuid'])
        return compute_utils.get_device_name_for_instance(
                self.context, self.instance, bdms, device)

    @staticmethod
    def _fake_bdm(device):
        return fake_block_device.FakeDbBlockDeviceDict({
            'source_type': 'volume',
            'destination_type': 'volume',
            'device_name': device,
            'no_device': None,
            'volume_id': 'fake',
            'snapshot_id': None,
            'guest_format': None
        })

    def test_wrap(self):
        self.data = []
        for letter in string.ascii_lowercase[2:]:
            self.data.append(self._fake_bdm('/dev/vd' + letter))
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdaa')

    def test_wrap_plus_one(self):
        self.data = []
        for letter in string.ascii_lowercase[2:]:
            self.data.append(self._fake_bdm('/dev/vd' + letter))
        self.data.append(self._fake_bdm('/dev/vdaa'))
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdab')

    def test_later(self):
        self.data = [
            self._fake_bdm('/dev/vdc'),
            self._fake_bdm('/dev/vdd'),
            self._fake_bdm('/dev/vde'),
        ]
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdf')

    def test_gap(self):
        self.data = [
            self._fake_bdm('/dev/vdc'),
            self._fake_bdm('/dev/vde'),
        ]
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdd')

    def test_no_bdms(self):
        self.data = []
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdc')

    def test_lxc_names_work(self):
        self.instance['root_device_name'] = '/dev/a'
        self.instance['ephemeral_device_name'] = '/dev/b'
        self.data = []
        device = self._validate_device()
        self.assertEqual(device, '/dev/c')

    def test_name_conversion(self):
        self.data = []
        device = self._validate_device('/dev/c')
        self.assertEqual(device, '/dev/vdc')
        device = self._validate_device('/dev/sdc')
        self.assertEqual(device, '/dev/vdc')
        device = self._validate_device('/dev/xvdc')
        self.assertEqual(device, '/dev/vdc')

    def test_invalid_bdms(self):
        self.instance['root_device_name'] = "baddata"
        self.assertRaises(exception.InvalidDevicePath,
                          self._validate_device)

    def test_invalid_device_prefix(self):
        self.assertRaises(exception.InvalidDevicePath,
                          self._validate_device, '/baddata/vdc')

    def test_device_in_use(self):
        exc = self.assertRaises(exception.DevicePathInUse,
                          self._validate_device, '/dev/vda')
        self.assertIn('/dev/vda', str(exc))

    def test_swap(self):
        self.instance['default_swap_device'] = "/dev/vdc"
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdd')

    def test_swap_no_ephemeral(self):
        del self.instance['default_ephemeral_device']
        self.instance['default_swap_device'] = "/dev/vdb"
        device = self._validate_device()
        self.assertEqual(device, '/dev/vdc')

    def test_ephemeral_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 10,
                'swap': 0,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdc')

    def test_swap_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 0,
                'swap': 10,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdb')

    def test_swap_and_ephemeral_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 10,
                'swap': 10,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdd')

    def test_swap_and_one_attachment_xenapi(self):
        self._update_flavor({
                'ephemeral_gb': 0,
                'swap': 10,
                })
        self.stubs.Set(flavors, 'get_flavor',
                       lambda instance_type_id, ctxt=None: self.flavor)
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdb')
        self.data.append(self._fake_bdm(device))
        device = self._validate_device()
        self.assertEqual(device, '/dev/xvdd')


class DefaultDeviceNamesForInstanceTestCase(test.NoDBTestCase):

    def setUp(self):
        super(DefaultDeviceNamesForInstanceTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.ephemerals = block_device_obj.block_device_make_list(
                self.context,
                [fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 1, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vdb',
                  'source_type': 'blank',
                  'destination_type': 'local',
                  'delete_on_termination': True,
                  'guest_format': None,
                  'boot_index': -1})])

        self.swap = block_device_obj.block_device_make_list(
                self.context,
                [fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 2, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vdc',
                  'source_type': 'blank',
                  'destination_type': 'local',
                  'delete_on_termination': True,
                  'guest_format': 'swap',
                  'boot_index': -1})])

        self.block_device_mapping = block_device_obj.block_device_make_list(
                self.context,
                [fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 3, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vda',
                  'source_type': 'volume',
                  'destination_type': 'volume',
                  'volume_id': 'fake-volume-id-1',
                  'boot_index': 0}),
                 fake_block_device.FakeDbBlockDeviceDict(
                 {'id': 4, 'instance_uuid': 'fake-instance',
                  'device_name': '/dev/vdd',
                  'source_type': 'snapshot',
                  'destination_type': 'volume',
                  'snapshot_id': 'fake-snapshot-id-1',
                  'boot_index': -1})])
        self.flavor = {'swap': 4}
        self.instance = {'uuid': 'fake_instance', 'ephemeral_gb': 2}
        self.is_libvirt = False
        self.root_device_name = '/dev/vda'
        self.update_called = False

        def fake_extract_flavor(instance):
            return self.flavor

        def fake_driver_matches(driver_string):
            if driver_string == 'libvirt.LibvirtDriver':
                return self.is_libvirt
            return False

        self.patchers = []
        self.patchers.append(
                mock.patch.object(block_device_obj.BlockDeviceMapping, 'save'))
        self.patchers.append(
                mock.patch.object(
                    flavors, 'extract_flavor',
                    new=mock.Mock(side_effect=fake_extract_flavor)))
        self.patchers.append(
                mock.patch.object(driver,
                                  'compute_driver_matches',
                                  new=mock.Mock(
                                      side_effect=fake_driver_matches)))
        for patcher in self.patchers:
            patcher.start()

    def tearDown(self):
        super(DefaultDeviceNamesForInstanceTestCase, self).tearDown()
        for patcher in self.patchers:
            patcher.stop()

    def _test_default_device_names(self, *block_device_lists):
        compute_utils.default_device_names_for_instance(self.instance,
                                                        self.root_device_name,
                                                        *block_device_lists)

    def test_only_block_device_mapping(self):
        # Test no-op
        original_bdm = copy.deepcopy(self.block_device_mapping)
        self._test_default_device_names([], [], self.block_device_mapping)
        for original, new in zip(original_bdm, self.block_device_mapping):
            self.assertEqual(original.device_name, new.device_name)

        # Asser it defaults the missing one as expected
        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names([], [], self.block_device_mapping)
        self.assertEqual(self.block_device_mapping[1]['device_name'],
                         '/dev/vdb')

    def test_with_ephemerals(self):
        # Test ephemeral gets assigned
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual(self.ephemerals[0]['device_name'], '/dev/vdb')

        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names(self.ephemerals, [],
                                        self.block_device_mapping)
        self.assertEqual(self.block_device_mapping[1]['device_name'],
                         '/dev/vdc')

    def test_with_swap(self):
        # Test swap only
        self.swap[0]['device_name'] = None
        self._test_default_device_names([], self.swap, [])
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdb')

        # Test swap and block_device_mapping
        self.swap[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names([], self.swap,
                                        self.block_device_mapping)
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdb')
        self.assertEqual(self.block_device_mapping[1]['device_name'],
                         '/dev/vdc')

    def test_all_together(self):
        # Test swap missing
        self.swap[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdc')

        # Test swap and eph missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual(self.ephemerals[0]['device_name'], '/dev/vdb')
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdc')

        # Test all missing
        self.swap[0]['device_name'] = None
        self.ephemerals[0]['device_name'] = None
        self.block_device_mapping[1]['device_name'] = None
        self._test_default_device_names(self.ephemerals,
                                        self.swap, self.block_device_mapping)
        self.assertEqual(self.ephemerals[0]['device_name'], '/dev/vdb')
        self.assertEqual(self.swap[0]['device_name'], '/dev/vdc')
        self.assertEqual(self.block_device_mapping[1]['device_name'],
                         '/dev/vdd')


class UsageInfoTestCase(test.TestCase):

    def setUp(self):
        def fake_get_nw_info(cls, ctxt, instance):
            self.assertTrue(ctxt.is_admin)
            return fake_network.fake_get_instance_nw_info(self.stubs, 1, 1)

        super(UsageInfoTestCase, self).setUp()
        self.stubs.Set(network_api.API, 'get_instance_nw_info',
                       fake_get_nw_info)

        fake_notifier.stub_notifier(self.stubs)
        self.addCleanup(fake_notifier.reset)

        self.flags(use_local=True, group='conductor')
        self.flags(compute_driver='nova.virt.fake.FakeDriver',
                   network_manager='nova.network.manager.FlatManager')
        self.compute = importutils.import_object(CONF.compute_manager)
        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id, self.project_id)

        def fake_show(meh, context, id):
            return {'id': 1, 'properties': {'kernel_id': 1, 'ramdisk_id': 1}}

        self.stubs.Set(nova.tests.image.fake._FakeImageService,
                       'show', fake_show)
        fake_network.set_stub_network_methods(self.stubs)
        fake_instance_actions.stub_out_action_events(self.stubs)

    def _create_instance(self, params={}):
        """Create a test instance."""
        flavor = flavors.get_flavor_by_name('m1.tiny')
        sys_meta = flavors.save_flavor_info({}, flavor)
        inst = {}
        inst['image_ref'] = 1
        inst['reservation_id'] = 'r-fakeres'
        inst['user_id'] = self.user_id
        inst['project_id'] = self.project_id
        inst['instance_type_id'] = flavor['id']
        inst['system_metadata'] = sys_meta
        inst['ami_launch_index'] = 0
        inst['root_gb'] = 0
        inst['ephemeral_gb'] = 0
        inst['info_cache'] = {'network_info': '[]'}
        inst.update(params)
        return db.instance_create(self.context, inst)['id']

    def test_notify_usage_exists(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = instance_obj.Instance.get_by_id(self.context, instance_id)
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        instance.system_metadata.update(sys_metadata)
        instance.save()
        compute_utils.notify_usage_exists(
            rpc.get_notifier('compute'), self.context, instance)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.exists')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance, [], [])

    def test_notify_usage_exists_deleted_instance(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = instance_obj.Instance.get_by_id(self.context, instance_id,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        instance.system_metadata.update(sys_metadata)
        instance.save()
        self.compute.terminate_instance(self.context, instance, [], [])
        instance = instance_obj.Instance.get_by_id(
                self.context.elevated(read_deleted='yes'), instance_id,
                expected_attrs=['system_metadata'])
        compute_utils.notify_usage_exists(
            rpc.get_notifier('compute'), self.context, instance)
        msg = fake_notifier.NOTIFICATIONS[-1]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.exists')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)

    def test_notify_usage_exists_instance_not_found(self):
        # Ensure 'exists' notification generates appropriate usage data.
        instance_id = self._create_instance()
        instance = instance_obj.Instance.get_by_id(self.context, instance_id,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        self.compute.terminate_instance(self.context, instance, [], [])
        compute_utils.notify_usage_exists(
            rpc.get_notifier('compute'), self.context, instance)
        msg = fake_notifier.NOTIFICATIONS[-1]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.exists')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description',
                     'bandwidth', 'audit_period_beginning',
                     'audit_period_ending', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'], {})
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)

    def test_notify_about_instance_usage(self):
        instance_id = self._create_instance()
        instance = instance_obj.Instance.get_by_id(self.context, instance_id,
                expected_attrs=['metadata', 'system_metadata', 'info_cache'])
        # Set some system metadata
        sys_metadata = {'image_md_key1': 'val1',
                        'image_md_key2': 'val2',
                        'other_data': 'meow'}
        instance.system_metadata.update(sys_metadata)
        instance.save()
        extra_usage_info = {'image_name': 'fake_name'}
        compute_utils.notify_about_instance_usage(
            rpc.get_notifier('compute'),
            self.context, instance, 'create.start',
            extra_usage_info=extra_usage_info)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'compute.instance.create.start')
        payload = msg.payload
        self.assertEqual(payload['tenant_id'], self.project_id)
        self.assertEqual(payload['user_id'], self.user_id)
        self.assertEqual(payload['instance_id'], instance['uuid'])
        self.assertEqual(payload['instance_type'], 'm1.tiny')
        type_id = flavors.get_flavor_by_name('m1.tiny')['id']
        self.assertEqual(str(payload['instance_type_id']), str(type_id))
        flavor_id = flavors.get_flavor_by_name('m1.tiny')['flavorid']
        self.assertEqual(str(payload['instance_flavor_id']), str(flavor_id))
        for attr in ('display_name', 'created_at', 'launched_at',
                     'state', 'state_description', 'image_meta'):
            self.assertTrue(attr in payload,
                            msg="Key %s not in payload" % attr)
        self.assertEqual(payload['image_meta'],
                {'md_key1': 'val1', 'md_key2': 'val2'})
        self.assertEqual(payload['image_name'], 'fake_name')
        image_ref_url = "%s/images/1" % glance.generate_glance_url()
        self.assertEqual(payload['image_ref_url'], image_ref_url)
        self.compute.terminate_instance(self.context, instance, [], [])

    def test_notify_about_aggregate_update_with_id(self):
        # Set aggregate payload
        aggregate_payload = {'aggregate_id': 1}
        compute_utils.notify_about_aggregate_update(self.context,
                                                    "create.end",
                                                    aggregate_payload)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'aggregate.create.end')
        payload = msg.payload
        self.assertEqual(payload['aggregate_id'], 1)

    def test_notify_about_aggregate_update_with_name(self):
        # Set aggregate payload
        aggregate_payload = {'name': 'fakegroup'}
        compute_utils.notify_about_aggregate_update(self.context,
                                                    "create.start",
                                                    aggregate_payload)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 1)
        msg = fake_notifier.NOTIFICATIONS[0]
        self.assertEqual(msg.priority, 'INFO')
        self.assertEqual(msg.event_type, 'aggregate.create.start')
        payload = msg.payload
        self.assertEqual(payload['name'], 'fakegroup')

    def test_notify_about_aggregate_update_without_name_id(self):
        # Set empty aggregate payload
        aggregate_payload = {}
        compute_utils.notify_about_aggregate_update(self.context,
                                                    "create.start",
                                                    aggregate_payload)
        self.assertEqual(len(fake_notifier.NOTIFICATIONS), 0)


class ComputeGetImageMetadataTestCase(test.TestCase):
    def setUp(self):
        super(ComputeGetImageMetadataTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')

        self.image = {
            "min_ram": 10,
            "min_disk": 1,
            "disk_format": "raw",
            "container_format": "bare",
            "properties": {},
        }

        self.image_service = nova.tests.image.fake._FakeImageService()
        self.stubs.Set(self.image_service, 'show', self._fake_show)

        self.ctx = context.RequestContext('fake', 'fake')

        sys_meta = {
            'image_min_ram': 10,
            'image_min_disk': 1,
            'image_disk_format': 'raw',
            'image_container_format': 'bare',
            'instance_type_id': 0,
            'instance_type_name': 'm1.fake',
            'instance_type_memory_mb': 10,
            'instance_type_vcpus': 1,
            'instance_type_root_gb': 1,
            'instance_type_ephemeral_gb': 1,
            'instance_type_flavorid': '0',
            'instance_type_swap': 1,
            'instance_type_rxtx_factor': 0.0,
            'instance_type_vcpu_weight': None,
        }

        self.instance = fake_instance.fake_db_instance(
            memory_mb=0, root_gb=0,
            system_metadata=sys_meta)

    @property
    def instance_obj(self):
        return instance_obj.Instance._from_db_object(
            self.ctx, instance_obj.Instance(), self.instance,
            expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS)

    def _fake_show(self, ctx, image_id):
        return self.image

    def test_get_image_meta(self):
        image_meta = compute_utils.get_image_metadata(
            self.ctx, self.image_service, 'fake-image', self.instance_obj)

        self.image['properties'] = 'DONTCARE'
        self.assertThat(self.image, matchers.DictMatches(image_meta))

    def test_get_image_meta_no_image(self):
        def fake_show(ctx, image_id):
            raise exception.ImageNotFound(image_id='fake-image')

        self.stubs.Set(self.image_service, 'show', fake_show)

        image_meta = compute_utils.get_image_metadata(
            self.ctx, self.image_service, 'fake-image', self.instance_obj)

        self.image['properties'] = 'DONTCARE'
        # NOTE(danms): The trip through system_metadata will stringify things
        for key in self.image:
            self.image[key] = str(self.image[key])
        self.assertThat(self.image, matchers.DictMatches(image_meta))

    def test_get_image_meta_no_image_system_meta(self):
        for k in self.instance['system_metadata'].keys():
            if k.startswith('image_'):
                del self.instance['system_metadata'][k]

        image_meta = compute_utils.get_image_metadata(
            self.ctx, self.image_service, 'fake-image', self.instance_obj)

        self.image['properties'] = 'DONTCARE'
        self.assertThat(self.image, matchers.DictMatches(image_meta))

    def test_get_image_meta_no_image_no_image_system_meta(self):
        def fake_show(ctx, image_id):
            raise exception.ImageNotFound(image_id='fake-image')

        self.stubs.Set(self.image_service, 'show', fake_show)

        for k in self.instance['system_metadata'].keys():
            if k.startswith('image_'):
                del self.instance['system_metadata'][k]

        image_meta = compute_utils.get_image_metadata(
            self.ctx, self.image_service, 'fake-image', self.instance_obj)

        expected = {'properties': 'DONTCARE'}
        self.assertThat(expected, matchers.DictMatches(image_meta))


class ComputeUtilsGetNWInfo(test.TestCase):
    def test_instance_object_none_info_cache(self):
        inst = fake_instance.fake_instance_obj('fake-context',
                                               expected_attrs=['info_cache'])
        self.assertIsNone(inst.info_cache)
        result = compute_utils.get_nw_info_for_instance(inst)
        self.assertEqual(jsonutils.dumps([]), result.json())

    def test_instance_dict_none_info_cache(self):
        inst = fake_instance.fake_db_instance(info_cache=None)
        self.assertIsNone(inst['info_cache'])
        result = compute_utils.get_nw_info_for_instance(inst)
        self.assertEqual(jsonutils.dumps([]), result.json())


class ComputeUtilsGetRebootTypes(test.TestCase):
    def setUp(self):
        super(ComputeUtilsGetRebootTypes, self).setUp()
        self.context = context.RequestContext('fake', 'fake')

    def test_get_reboot_type_started_soft(self):
        reboot_type = compute_utils.get_reboot_type(task_states.REBOOT_STARTED,
                                                    power_state.RUNNING)
        self.assertEqual(reboot_type, 'SOFT')

    def test_get_reboot_type_pending_soft(self):
        reboot_type = compute_utils.get_reboot_type(task_states.REBOOT_PENDING,
                                                    power_state.RUNNING)
        self.assertEqual(reboot_type, 'SOFT')

    def test_get_reboot_type_hard(self):
        reboot_type = compute_utils.get_reboot_type('foo', power_state.RUNNING)
        self.assertEqual(reboot_type, 'HARD')

    def test_get_reboot_not_running_hard(self):
        reboot_type = compute_utils.get_reboot_type('foo', 'bar')
        self.assertEqual(reboot_type, 'HARD')
