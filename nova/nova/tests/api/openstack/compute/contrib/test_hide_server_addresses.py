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

import itertools

from lxml import etree
import webob

from nova.api.openstack import wsgi
from nova import compute
from nova.compute import vm_states
from nova import db
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


SENTINEL = object()


def fake_compute_get(*args, **kwargs):
    def _return_server(*_args, **_kwargs):
        inst = fakes.stub_instance(*args, **kwargs)
        return fake_instance.fake_instance_obj(_args[1], **inst)
    return _return_server


class HideServerAddressesTest(test.TestCase):
    content_type = 'application/json'

    def setUp(self):
        super(HideServerAddressesTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Hide_server_addresses'])
        return_server = fakes.fake_instance_get()
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app(init_only=('servers',)))
        return res

    @staticmethod
    def _get_server(body):
        return jsonutils.loads(body).get('server')

    @staticmethod
    def _get_servers(body):
        return jsonutils.loads(body).get('servers')

    @staticmethod
    def _get_addresses(server):
        return server.get('addresses', SENTINEL)

    def _check_addresses(self, addresses, exists):
        self.assertTrue(addresses is not SENTINEL)
        if exists:
            self.assertTrue(addresses)
        else:
            self.assertFalse(addresses)

    def test_show_hides_in_building(self):
        instance_id = 1
        uuid = fakes.get_fake_uuid(instance_id)
        self.stubs.Set(compute.api.API, 'get',
                       fake_compute_get(instance_id, uuid=uuid,
                                        vm_state=vm_states.BUILDING))
        res = self._make_request('/v2/fake/servers/%s' % uuid)
        self.assertEqual(res.status_int, 200)

        server = self._get_server(res.body)
        addresses = self._get_addresses(server)
        self._check_addresses(addresses, exists=False)

    def test_show(self):
        instance_id = 1
        uuid = fakes.get_fake_uuid(instance_id)
        self.stubs.Set(compute.api.API, 'get',
                       fake_compute_get(instance_id, uuid=uuid,
                                        vm_state=vm_states.ACTIVE))
        res = self._make_request('/v2/fake/servers/%s' % uuid)
        self.assertEqual(res.status_int, 200)

        server = self._get_server(res.body)
        addresses = self._get_addresses(server)
        self._check_addresses(addresses, exists=True)

    def test_detail_hides_building_server_addresses(self):
        instance_0 = fakes.stub_instance(0, uuid=fakes.get_fake_uuid(0),
                                         vm_state=vm_states.ACTIVE)
        instance_1 = fakes.stub_instance(1, uuid=fakes.get_fake_uuid(1),
                                         vm_state=vm_states.BUILDING)
        instances = [instance_0, instance_1]

        def get_all(*args, **kwargs):
            fields = instance_obj.INSTANCE_DEFAULT_FIELDS
            return instance_obj._make_instance_list(
                args[1], instance_obj.InstanceList(), instances, fields)

        self.stubs.Set(compute.api.API, 'get_all', get_all)
        res = self._make_request('/v2/fake/servers/detail')

        self.assertEqual(res.status_int, 200)
        servers = self._get_servers(res.body)

        self.assertEqual(len(servers), len(instances))

        for instance, server in itertools.izip(instances, servers):
            addresses = self._get_addresses(server)
            exists = (instance['vm_state'] == vm_states.ACTIVE)
            self._check_addresses(addresses, exists=exists)

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        res = self._make_request('/v2/fake/servers/' + fakes.get_fake_uuid())

        self.assertEqual(res.status_int, 404)


class HideAddressesXmlTest(HideServerAddressesTest):
    content_type = 'application/xml'

    @staticmethod
    def _get_server(body):
        return etree.XML(body)

    @staticmethod
    def _get_servers(body):
        return etree.XML(body).getchildren()

    @staticmethod
    def _get_addresses(server):
        addresses = server.find('{%s}addresses' % wsgi.XMLNS_V11)
        if addresses is None:
            return SENTINEL
        return addresses
