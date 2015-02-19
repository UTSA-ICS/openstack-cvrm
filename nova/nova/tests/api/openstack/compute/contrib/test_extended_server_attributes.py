# Copyright 2011 OpenStack Foundation
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

from lxml import etree
import webob

from nova.api.openstack.compute.contrib import extended_server_attributes
from nova import compute
from nova import db
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes

from oslo.config import cfg


NAME_FMT = cfg.CONF.instance_name_template
UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'


def fake_compute_get(*args, **kwargs):
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj.Instance._from_db_object(
        args[1], instance_obj.Instance(),
        fakes.stub_instance(1, uuid=UUID3, host="host-fake",
                            node="node-fake"), fields)


def fake_compute_get_all(*args, **kwargs):
    db_list = [
        fakes.stub_instance(1, uuid=UUID1, host="host-1", node="node-1"),
        fakes.stub_instance(2, uuid=UUID2, host="host-2", node="node-2")
    ]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            instance_obj.InstanceList(),
                                            db_list, fields)


class ExtendedServerAttributesTest(test.TestCase):
    content_type = 'application/json'
    prefix = 'OS-EXT-SRV-ATTR:'

    def setUp(self):
        super(ExtendedServerAttributesTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        self.stubs.Set(db, 'instance_get_by_uuid', fake_compute_get)
        self.flags(
            osapi_compute_extension=[
                'nova.api.openstack.compute.contrib.select_extensions'],
            osapi_compute_ext_list=['Extended_server_attributes'])

    def _make_request(self, url):
        req = webob.Request.blank(url)
        req.headers['Accept'] = self.content_type
        res = req.get_response(fakes.wsgi_app(init_only=('servers',)))
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def assertServerAttributes(self, server, host, node, instance_name):
        self.assertEqual(server.get('%shost' % self.prefix), host)
        self.assertEqual(server.get('%sinstance_name' % self.prefix),
                         instance_name)
        self.assertEqual(server.get('%shypervisor_hostname' % self.prefix),
                         node)

    def test_show(self):
        url = '/v2/fake/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        self.assertServerAttributes(self._get_server(res.body),
                                host='host-fake',
                                node='node-fake',
                                instance_name=NAME_FMT % 1)

    def test_detail(self):
        url = '/v2/fake/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        for i, server in enumerate(self._get_servers(res.body)):
            self.assertServerAttributes(server,
                                    host='host-%s' % (i + 1),
                                    node='node-%s' % (i + 1),
                                    instance_name=NAME_FMT % (i + 1))

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        url = '/v2/fake/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)


class ExtendedServerAttributesXmlTest(ExtendedServerAttributesTest):
    content_type = 'application/xml'
    ext = extended_server_attributes
    prefix = '{%s}' % ext.Extended_server_attributes.namespace

    def _get_server(self, body):
        return etree.XML(body)

    def _get_servers(self, body):
        return etree.XML(body).getchildren()
