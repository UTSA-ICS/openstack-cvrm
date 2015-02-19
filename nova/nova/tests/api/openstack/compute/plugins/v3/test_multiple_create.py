# Copyright 2013 IBM Corp.
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

import datetime
import uuid

from oslo.config import cfg
import webob

from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import multiple_create
from nova.api.openstack.compute.plugins.v3 import servers
from nova.compute import api as compute_api
from nova.compute import flavors
from nova import db
from nova.network import manager
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests.image import fake

CONF = cfg.CONF
FAKE_UUID = fakes.FAKE_UUID


def fake_gen_uuid():
    return FAKE_UUID


def return_security_group(context, instance_id, security_group_id):
    pass


class ServersControllerCreateTest(test.TestCase):

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(verbose=True,
                   enable_instance_password=True)
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)
        CONF.set_override('extensions_blacklist', 'os-multiple-create',
                          'osapi_v3')
        self.no_mult_create_controller = servers.ServersController(
            extension_info=ext_info)

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': FAKE_UUID,
                'instance_type': dict(inst_type),
                'access_ip_v4': '1.2.3.4',
                'access_ip_v6': 'fead::1234',
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
                "security_groups": inst['security_groups'],
            })

            self.instance_cache_by_id[instance['id']] = instance
            self.instance_cache_by_uuid[instance['uuid']] = instance
            return instance

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache_by_id[instance_id]

        def instance_update(context, uuid, values):
            instance = self.instance_cache_by_uuid[uuid]
            instance.update(values)
            return instance

        def server_update(context, instance_uuid, params, update_cells=True,
                          columns_to_join=None):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return (inst, inst)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fake.stub_out_image_service(self.stubs)
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(uuid, 'uuid4', fake_gen_uuid)
        self.stubs.Set(db, 'instance_add_security_group',
                       return_security_group)
        self.stubs.Set(db, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(db, 'instance_create', instance_create)
        self.stubs.Set(db, 'instance_system_metadata_update',
                       fake_method)
        self.stubs.Set(db, 'instance_get', instance_get)
        self.stubs.Set(db, 'instance_update', instance_update)
        self.stubs.Set(db, 'instance_update_and_get_original',
                       server_update)
        self.stubs.Set(manager.VlanManager, 'allocate_fixed_ip',
                       fake_method)

    def _test_create_extra(self, params, no_image=False,
                           override_controller=None):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        server = dict(name='server_test', image_ref=image_uuid, flavor_ref=2)
        if no_image:
            server.pop('image_ref', None)
        server.update(params)
        body = dict(server=server)
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        if override_controller:
            server = override_controller.create(req, body=body).obj['server']
        else:
            server = self.controller.create(req, body=body).obj['server']

    def test_create_instance_with_multiple_create_disabled(self):
        ret_res_id = True
        min_count = 2
        max_count = 3
        params = {
            multiple_create.MIN_ATTRIBUTE_NAME: min_count,
            multiple_create.MAX_ATTRIBUTE_NAME: max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertNotIn('min_count', kwargs)
            self.assertNotIn('max_count', kwargs)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(
            params,
            override_controller=self.no_mult_create_controller)

    def test_multiple_create_with_string_type_min_and_max(self):
        min_count = '2'
        max_count = '3'
        params = {
            multiple_create.MIN_ATTRIBUTE_NAME: min_count,
            multiple_create.MAX_ATTRIBUTE_NAME: max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsInstance(kwargs['min_count'], int)
            self.assertIsInstance(kwargs['max_count'], int)
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['max_count'], 3)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_multiple_create_enabled(self):
        min_count = 2
        max_count = 3
        params = {
            multiple_create.MIN_ATTRIBUTE_NAME: min_count,
            multiple_create.MAX_ATTRIBUTE_NAME: max_count,
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['max_count'], 3)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_invalid_negative_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create.MIN_ATTRIBUTE_NAME: -1,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
            }
        }
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    def test_create_instance_invalid_negative_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create.MAX_ATTRIBUTE_NAME: -1,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
            }
        }
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    def test_create_instance_invalid_min_greater_than_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create.MIN_ATTRIBUTE_NAME: 4,
                multiple_create.MAX_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
            }
        }
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    def test_create_instance_invalid_alpha_min(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create.MIN_ATTRIBUTE_NAME: 'abcd',
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
            }
        }
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    def test_create_instance_invalid_alpha_max(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'

        body = {
            'server': {
                multiple_create.MAX_ATTRIBUTE_NAME: 'abcd',
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
            }
        }
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          req,
                          body=body)

    def test_create_multiple_instances(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create.MIN_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body=body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_password_len(res["server"])

    def test_create_multiple_instances_pass_disabled(self):
        """Test creating multiple instances but not asking for
        reservation_id
        """
        self.flags(enable_instance_password=False)
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create.MIN_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body=body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_password_missing(res["server"])

    def _check_admin_password_len(self, server_dict):
        """utility function - check server_dict for admin_password length."""
        self.assertEqual(CONF.password_length,
                         len(server_dict["admin_password"]))

    def _check_admin_password_missing(self, server_dict):
        """utility function - check server_dict for admin_password absence."""
        self.assertNotIn("admin_password", server_dict)

    def _create_multiple_instances_resv_id_return(self, resv_id_return):
        """Test creating multiple instances with asking for
        reservation_id
        """
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create.MIN_ATTRIBUTE_NAME: 2,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
                multiple_create.RRID_ATTRIBUTE_NAME: resv_id_return
            }
        }

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        res = self.controller.create(req, body=body)
        reservation_id = res.obj['servers_reservation']['reservation_id']
        self.assertNotEqual(reservation_id, "")
        self.assertIsNotNone(reservation_id)
        self.assertTrue(len(reservation_id) > 1)

    def test_create_multiple_instances_with_resv_id_return(self):
        self._create_multiple_instances_resv_id_return(True)

    def test_create_multiple_instances_with_string_resv_id_return(self):
        self._create_multiple_instances_resv_id_return("True")

    def test_create_multiple_instances_with_multiple_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested with a list of block device mappings for volumes.
        """
        min_count = 2
        bdm = [{'device_name': 'foo1', 'volume_id': 'vol-xxxx'},
               {'device_name': 'foo2', 'volume_id': 'vol-yyyy'}
        ]
        params = {
                  'block_device_mapping': bdm,
                  'min_count': min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(len(kwargs['block_device_mapping']), 2)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params, no_image=True)

    def test_create_multiple_instances_with_single_volume_bdm(self):
        """Test that a BadRequest is raised if multiple instances
        are requested to boot from a single volume.
        """
        min_count = 2
        bdm = [{'device_name': 'foo1', 'volume_id': 'vol-xxxx'}]
        params = {
                 'block_device_mapping': bdm,
                 multiple_create.MIN_ATTRIBUTE_NAME: min_count
        }
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertEqual(kwargs['min_count'], 2)
            self.assertEqual(kwargs['block_device_mapping']['volume_id'],
                            'vol-xxxx')
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params, no_image=True)

    def test_create_multiple_instance_with_non_integer_max_count(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create.MAX_ATTRIBUTE_NAME: 2.5,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body=body)

    def test_create_multiple_instance_with_non_integer_min_count(self):
        image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                multiple_create.MIN_ATTRIBUTE_NAME: 2.5,
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {'hello': 'world',
                             'open': 'stack'},
            }
        }

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body=body)
