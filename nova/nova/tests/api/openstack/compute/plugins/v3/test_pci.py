# Copyright 2013 Intel Corp.
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


from webob import exc

from nova.api.openstack.compute.plugins.v3 import pci
from nova.api.openstack import wsgi
from nova import context
from nova import db
from nova import exception
from nova.objects import instance
from nova.objects import pci_device
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests.objects import test_pci_device


fake_compute_node = {
    'pci_stats': [{"count": 3,
                   "vendor_id": "8086",
                   "product_id": "1520",
                   "extra_info": {"phys_function": '[["0x0000", "0x04", '
                                                   '"0x00", "0x1"]]'}}]}


class FakeResponse(wsgi.ResponseObject):
    pass


class PciServerControllerTest(test.NoDBTestCase):
    def setUp(self):
        super(PciServerControllerTest, self).setUp()
        self.controller = pci.PciServerController()
        self.fake_obj = {'server': {'addresses': {},
                                    'id': 'fb08',
                                    'name': 'a3',
                                    'status': 'ACTIVE',
                                    'tenant_id': '9a3af784c',
                                    'user_id': 'e992080ac0',
                                    }}
        self.fake_list = {'servers': [{'addresses': {},
                                       'id': 'fb08',
                                       'name': 'a3',
                                       'status': 'ACTIVE',
                                       'tenant_id': '9a3af784c',
                                       'user_id': 'e992080ac',
                                       }]}
        self._create_fake_instance()
        self._create_fake_pci_device()
        self.pci_device.claim(self.inst)
        self.pci_device.allocate(self.inst)

    def _create_fake_instance(self):
        self.inst = instance.Instance()
        self.inst.uuid = 'fake-inst-uuid'
        self.inst.pci_devices = pci_device.PciDeviceList()

    def _create_fake_pci_device(self):
        def fake_pci_device_get_by_addr(ctxt, id, addr):
            return test_pci_device.fake_db_dev

        ctxt = context.get_admin_context()
        self.stubs.Set(db, 'pci_device_get_by_addr',
                       fake_pci_device_get_by_addr)
        self.pci_device = pci_device.PciDevice.get_by_dev_addr(ctxt, 1, 'a')

    def test_show(self):
        def fake_get_db_instance(id):
            return self.inst

        resp = FakeResponse(self.fake_obj, '')
        req = fakes.HTTPRequestV3.blank('/os-pci/1', use_admin_context=True)
        self.stubs.Set(req, 'get_db_instance', fake_get_db_instance)
        self.controller.show(req, resp, '1')
        self.assertEqual([{'id': 1}],
                         resp.obj['server']['os-pci:pci_devices'])

    def test_detail(self):
        def fake_get_db_instance(id):
            return self.inst

        resp = FakeResponse(self.fake_list, '')
        req = fakes.HTTPRequestV3.blank('/os-pci/detail',
                                        use_admin_context=True)
        self.stubs.Set(req, 'get_db_instance', fake_get_db_instance)
        self.controller.detail(req, resp)
        self.assertEqual([{'id': 1}],
                         resp.obj['servers'][0]['os-pci:pci_devices'])


class PciHypervisorControllerTest(test.NoDBTestCase):
    def setUp(self):
        super(PciHypervisorControllerTest, self).setUp()
        self.controller = pci.PciHypervisorController()
        self.fake_objs = dict(hypervisors=[
            dict(id=1,
                 service=dict(id=1, host="compute1"),
                 hypervisor_type="xen",
                 hypervisor_version=3,
                 hypervisor_hostname="hyper1")])
        self.fake_obj = dict(hypervisor=dict(
            id=1,
            service=dict(id=1, host="compute1"),
            hypervisor_type="xen",
            hypervisor_version=3,
            hypervisor_hostname="hyper1"))

    def test_show(self):
        def fake_get_db_compute_node(id):
            fake_compute_node['pci_stats'] = jsonutils.dumps(
                fake_compute_node['pci_stats'])
            return fake_compute_node

        req = fakes.HTTPRequestV3.blank('/os-hypervisors/1',
                                        use_admin_context=True)
        resp = FakeResponse(self.fake_obj, '')
        self.stubs.Set(req, 'get_db_compute_node', fake_get_db_compute_node)
        self.controller.show(req, resp, '1')
        self.assertIn('os-pci:pci_stats', resp.obj['hypervisor'])
        fake_compute_node['pci_stats'] = jsonutils.loads(
            fake_compute_node['pci_stats'])
        self.assertEqual(fake_compute_node['pci_stats'][0],
                         resp.obj['hypervisor']['os-pci:pci_stats'][0])

    def test_detail(self):
        def fake_get_db_compute_node(id):
            fake_compute_node['pci_stats'] = jsonutils.dumps(
                fake_compute_node['pci_stats'])
            return fake_compute_node

        req = fakes.HTTPRequestV3.blank('/os-hypervisors/detail',
                                        use_admin_context=True)
        resp = FakeResponse(self.fake_objs, '')
        self.stubs.Set(req, 'get_db_compute_node', fake_get_db_compute_node)
        self.controller.detail(req, resp)
        fake_compute_node['pci_stats'] = jsonutils.loads(
            fake_compute_node['pci_stats'])
        self.assertIn('os-pci:pci_stats', resp.obj['hypervisors'][0])
        self.assertEqual(fake_compute_node['pci_stats'][0],
                         resp.obj['hypervisors'][0]['os-pci:pci_stats'][0])


class PciControlletest(test.NoDBTestCase):
    def setUp(self):
        super(PciControlletest, self).setUp()
        self.controller = pci.PciController()

    def test_show(self):
        def fake_pci_device_get_by_id(context, id):
            return test_pci_device.fake_db_dev

        self.stubs.Set(db, 'pci_device_get_by_id', fake_pci_device_get_by_id)
        req = fakes.HTTPRequestV3.blank('/os-pci/1', use_admin_context=True)
        result = self.controller.show(req, '1')
        dist = {'pci_device': {'address': 'a',
                               'compute_node_id': 1,
                               'dev_id': 'i',
                               'extra_info': {},
                               'dev_type': 't',
                               'id': 1,
                               'server_uuid': None,
                               'label': 'l',
                               'product_id': 'p',
                               'status': 'available',
                               'vendor_id': 'v'}}
        self.assertEqual(dist, result)

    def test_show_error_id(self):
        def fake_pci_device_get_by_id(context, id):
            raise exception.PciDeviceNotFoundById(id=id)

        self.stubs.Set(db, 'pci_device_get_by_id', fake_pci_device_get_by_id)
        req = fakes.HTTPRequestV3.blank('/os-pci/0', use_admin_context=True)
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, '0')

    def _fake_compute_node_get_all(self, context):
        return [dict(id=1,
                     service_id=1,
                     cpu_info='cpu_info',
                     disk_available_least=100)]

    def _fake_pci_device_get_all_by_node(self, context, node):
        return [test_pci_device.fake_db_dev, test_pci_device.fake_db_dev_1]

    def test_index(self):
        self.stubs.Set(db, 'compute_node_get_all',
                       self._fake_compute_node_get_all)
        self.stubs.Set(db, 'pci_device_get_all_by_node',
                       self._fake_pci_device_get_all_by_node)

        req = fakes.HTTPRequestV3.blank('/os-pci', use_admin_context=True)
        result = self.controller.index(req)
        dist = {'pci_devices': [test_pci_device.fake_db_dev,
                                test_pci_device.fake_db_dev_1]}
        for i in range(len(result['pci_devices'])):
            self.assertEqual(dist['pci_devices'][i]['vendor_id'],
                             result['pci_devices'][i]['vendor_id'])
            self.assertEqual(dist['pci_devices'][i]['id'],
                             result['pci_devices'][i]['id'])
            self.assertEqual(dist['pci_devices'][i]['status'],
                             result['pci_devices'][i]['status'])
            self.assertEqual(dist['pci_devices'][i]['address'],
                             result['pci_devices'][i]['address'])

    def test_detail(self):
        self.stubs.Set(db, 'compute_node_get_all',
                       self._fake_compute_node_get_all)
        self.stubs.Set(db, 'pci_device_get_all_by_node',
                       self._fake_pci_device_get_all_by_node)
        req = fakes.HTTPRequestV3.blank('/os-pci/detail',
                                        use_admin_context=True)
        result = self.controller.detail(req)
        dist = {'pci_devices': [test_pci_device.fake_db_dev,
                                test_pci_device.fake_db_dev_1]}
        for i in range(len(result['pci_devices'])):
            self.assertEqual(dist['pci_devices'][i]['vendor_id'],
                             result['pci_devices'][i]['vendor_id'])
            self.assertEqual(dist['pci_devices'][i]['id'],
                             result['pci_devices'][i]['id'])
            self.assertEqual(dist['pci_devices'][i]['label'],
                             result['pci_devices'][i]['label'])
            self.assertEqual(dist['pci_devices'][i]['dev_id'],
                             result['pci_devices'][i]['dev_id'])
