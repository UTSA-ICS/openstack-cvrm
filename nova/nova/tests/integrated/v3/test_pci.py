# Copyright 2013 Intel.
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

from nova import db
from nova.openstack.common import jsonutils
from nova.tests.integrated.v3 import api_sample_base
from nova.tests.integrated.v3 import test_servers


fake_db_dev_1 = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 1,
    'compute_node_id': 1,
    'address': '0000:04:10.0',
    'vendor_id': '8086',
    'product_id': '1520',
    'dev_type': 'type-VF',
    'status': 'available',
    'dev_id': 'pci_0000_04_10_0',
    'label': 'label_8086_1520',
    'instance_uuid': '69ba1044-0766-4ec0-b60d-09595de034a1',
    'extra_info': '{"key1": "value1", "key2": "value2"}'
    }

fake_db_dev_2 = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': None,
    'id': 2,
    'compute_node_id': 1,
    'address': '0000:04:10.1',
    'vendor_id': '8086',
    'product_id': '1520',
    'dev_type': 'type-VF',
    'status': 'available',
    'dev_id': 'pci_0000_04_10_1',
    'label': 'label_8086_1520',
    'instance_uuid': 'd5b446a6-a1b4-4d01-b4f0-eac37b3a62fc',
    'extra_info': '{"key3": "value3", "key4": "value4"}'
    }


class ExtendedServerPciSampleJsonTest(test_servers.ServersSampleBase):
    extension_name = "os-pci"

    def test_show(self):
        uuid = self._post_server()
        response = self._do_get('servers/%s' % uuid)
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('server-get-resp', subs, response, 200)

    def test_detail(self):
        self._post_server()
        response = self._do_get('servers/detail')
        subs = self._get_regexes()
        subs['hostid'] = '[a-f0-9]+'
        self._verify_response('servers-detail-resp', subs, response, 200)


class ExtendedHyervisorPciSampleJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extra_extensions_to_load = ['os-hypervisors']
    extension_name = 'os-pci'

    def setUp(self):
        super(ExtendedHyervisorPciSampleJsonTest, self).setUp()
        self.fake_compute_node = {"cpu_info": "?",
                                  "current_workload": 0,
                                  "disk_available_least": 0,
                                  "host_ip": "1.1.1.1",
                                  "free_disk_gb": 1028,
                                  "free_ram_mb": 7680,
                                  "hypervisor_hostname": "fake-mini",
                                  "hypervisor_type": "fake",
                                  "hypervisor_version": 1,
                                  "id": 1,
                                  "local_gb": 1028,
                                  "local_gb_used": 0,
                                  "memory_mb": 8192,
                                  "memory_mb_used": 512,
                                  "running_vms": 0,
                                  "service": {"host": '043b3cacf6f34c90a724'
                                                      '5151fc8ebcda'},
                                  "vcpus": 1,
                                  "vcpus_used": 0,
                                  "service_id": 2,
                                  "pci_stats": [
                                      {"count": 5,
                                       "vendor_id": "8086",
                                       "product_id": "1520",
                                       "keya": "valuea",
                                       "extra_info": {
                                           "phys_function": '[["0x0000", '
                                                            '"0x04", "0x00",'
                                                            ' "0x1"]]',
                                            "key1": "value1"}}]}

    def test_pci_show(self):
        def fake_compute_node_get(context, id):
            self.fake_compute_node['pci_stats'] = jsonutils.dumps(
                self.fake_compute_node['pci_stats'])
            return self.fake_compute_node

        self.stubs.Set(db, 'compute_node_get', fake_compute_node_get)
        hypervisor_id = 1
        response = self._do_get('os-hypervisors/%s' % hypervisor_id)
        subs = {
            'hypervisor_id': hypervisor_id,
        }
        subs.update(self._get_regexes())
        self._verify_response('hypervisors-pci-show-resp',
                              subs, response, 200)

    def test_pci_detail(self):
        def fake_compute_node_get_all(context):
            self.fake_compute_node['pci_stats'] = jsonutils.dumps(
                self.fake_compute_node['pci_stats'])
            return [self.fake_compute_node]

        self.stubs.Set(db, 'compute_node_get_all', fake_compute_node_get_all)
        hypervisor_id = 1
        subs = {
            'hypervisor_id': hypervisor_id
        }
        response = self._do_get('os-hypervisors/detail')

        subs.update(self._get_regexes())
        self._verify_response('hypervisors-pci-detail-resp',
                              subs, response, 200)


class PciSampleJsonTest(api_sample_base.ApiSampleTestBaseV3):
    extension_name = "os-pci"

    def _fake_pci_device_get_by_id(self, context, id):
        return fake_db_dev_1

    def _fake_pci_device_get_all_by_node(self, context, id):
        return [fake_db_dev_1, fake_db_dev_2]

    def test_pci_show(self):
        self.stubs.Set(db, 'pci_device_get_by_id',
                       self._fake_pci_device_get_by_id)
        response = self._do_get('os-pci/1')
        subs = self._get_regexes()
        self._verify_response('pci-show-resp', subs, response, 200)

    def test_pci_index(self):
        self.stubs.Set(db, 'pci_device_get_all_by_node',
                       self._fake_pci_device_get_all_by_node)
        response = self._do_get('os-pci')
        subs = self._get_regexes()
        self._verify_response('pci-index-resp', subs, response, 200)

    def test_pci_detail(self):
        self.stubs.Set(db, 'pci_device_get_all_by_node',
                       self._fake_pci_device_get_all_by_node)
        response = self._do_get('os-pci/detail')
        subs = self._get_regexes()
        self._verify_response('pci-detail-resp', subs, response, 200)
