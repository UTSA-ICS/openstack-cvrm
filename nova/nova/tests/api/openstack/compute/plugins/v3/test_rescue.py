#   Copyright 2011 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#       http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.

import mock
from oslo.config import cfg
import webob

from nova import compute
from nova import exception
from nova.openstack.common import jsonutils
from nova import test
from nova.tests.api.openstack import fakes

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')


def rescue(self, context, instance, rescue_password=None):
    pass


def unrescue(self, context, instance):
    pass


class RescueTest(test.NoDBTestCase):
    def setUp(self):
        super(RescueTest, self).setUp()

        def fake_compute_get(*args, **kwargs):
            uuid = '70f6db34-de8d-4fbd-aafb-4065bdfa6114'
            return {'id': 1, 'uuid': uuid}

        self.stubs.Set(compute.api.API, "get", fake_compute_get)
        self.stubs.Set(compute.api.API, "rescue", rescue)
        self.stubs.Set(compute.api.API, "unrescue", unrescue)
        self.app = fakes.wsgi_app_v3(init_only=('servers', 'os-rescue'))

    def test_rescue_with_preset_password(self):
        body = {"rescue": {"admin_password": "AABBCC112233"}}
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual("AABBCC112233", resp_json['admin_password'])

    def test_rescue_generates_password(self):
        body = dict(rescue=None)
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)
        resp_json = jsonutils.loads(resp.body)
        self.assertEqual(CONF.password_length,
                         len(resp_json['admin_password']))

    def test_rescue_with_none(self):
        body = dict(rescue=None)
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)

    def test_rescue_with_empty_dict(self):
        body = dict(rescue=dict())
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)

    def test_rescue_disable_password(self):
        self.flags(enable_instance_password=False)
        body = dict(rescue=None)
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)
        resp_json = jsonutils.loads(resp.body)
        self.assertNotIn('admin_password', resp_json)

    def test_rescue_of_rescued_instance(self):
        body = dict(rescue=None)

        def fake_rescue(*args, **kwargs):
            raise exception.InstanceInvalidState('fake message')

        self.stubs.Set(compute.api.API, "rescue", fake_rescue)
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(409, resp.status_int)

    def test_unrescue(self):
        body = dict(unrescue=None)
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(202, resp.status_int)

    def test_unrescue_of_active_instance(self):
        body = dict(unrescue=None)

        def fake_unrescue(*args, **kwargs):
            raise exception.InstanceInvalidState('fake message')

        self.stubs.Set(compute.api.API, "unrescue", fake_unrescue)
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(409, resp.status_int)

    def test_rescue_raises_unrescuable(self):
        body = dict(rescue=None)

        def fake_rescue(*args, **kwargs):
            raise exception.InstanceNotRescuable('fake message')

        self.stubs.Set(compute.api.API, "rescue", fake_rescue)
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(400, resp.status_int)

    def test_rescue_with_invalid_property(self):
        body = {"rescue": {"test": "test"}}
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(400, resp.status_int)

    @mock.patch('nova.compute.api.API.rescue')
    def test_rescue_raises_not_implemented(self, rescue_mock):
        body = dict(rescue=None)

        def fake_rescue(*args, **kwargs):
            raise NotImplementedError('fake message')

        rescue_mock.side_effect = fake_rescue
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 501)

    @mock.patch('nova.compute.api.API.unrescue')
    def test_unrescue_raises_not_implemented(self, unrescue_mock):
        body = dict(unrescue=None)

        def fake_unrescue(*args, **kwargs):
            raise NotImplementedError('fake message')

        unrescue_mock.side_effect = fake_unrescue
        req = webob.Request.blank('/v3/servers/test_inst/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        resp = req.get_response(self.app)
        self.assertEqual(resp.status_int, 501)
