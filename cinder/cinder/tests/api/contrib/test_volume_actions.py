#   Copyright 2012 OpenStack Foundation
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

import datetime
import json
import uuid

import mock
from oslo import messaging
import webob

from cinder.api.contrib import volume_actions
from cinder import exception
from cinder.openstack.common import jsonutils
from cinder import test
from cinder.tests.api import fakes
from cinder.tests.api.v2 import stubs
from cinder import volume
from cinder.volume import api as volume_api


class VolumeActionsTest(test.TestCase):

    _actions = ('os-detach', 'os-reserve', 'os-unreserve')

    _methods = ('attach', 'detach', 'reserve_volume', 'unreserve_volume')

    def setUp(self):
        super(VolumeActionsTest, self).setUp()
        self.UUID = uuid.uuid4()
        self.api_patchers = {}
        for _meth in self._methods:
            self.api_patchers[_meth] = mock.patch('cinder.volume.API.' + _meth)
            self.api_patchers[_meth].start()
            self.addCleanup(self.api_patchers[_meth].stop)
            self.api_patchers[_meth].return_value = True

        vol = {'id': 'fake', 'host': 'fake', 'status': 'available', 'size': 1,
               'migration_status': None, 'volume_type_id': 'fake'}
        self.get_patcher = mock.patch('cinder.volume.API.get')
        self.mock_volume_get = self.get_patcher.start()
        self.addCleanup(self.get_patcher.stop)
        self.mock_volume_get.return_value = vol
        self.update_patcher = mock.patch('cinder.volume.API.update')
        self.mock_volume_update = self.update_patcher.start()
        self.addCleanup(self.update_patcher.stop)
        self.mock_volume_update.return_value = vol

        self.flags(rpc_backend='cinder.openstack.common.rpc.impl_fake')

    def test_simple_api_actions(self):
        app = fakes.wsgi_app()
        for _action in self._actions:
            req = webob.Request.blank('/v2/fake/volumes/%s/action' %
                                      self.UUID)
            req.method = 'POST'
            req.body = jsonutils.dumps({_action: None})
            req.content_type = 'application/json'
            res = req.get_response(app)
            self.assertEqual(res.status_int, 202)

    def test_initialize_connection(self):
        with mock.patch.object(volume_api.API,
                               'initialize_connection') as init_conn:
            init_conn.return_value = {}
            body = {'os-initialize_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/fake/volumes/1/action')
            req.method = "POST"
            req.body = jsonutils.dumps(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app())
            self.assertEqual(res.status_int, 200)

    def test_initialize_connection_without_connector(self):
        with mock.patch.object(volume_api.API,
                               'initialize_connection') as init_conn:
            init_conn.return_value = {}
            body = {'os-initialize_connection': {}}
            req = webob.Request.blank('/v2/fake/volumes/1/action')
            req.method = "POST"
            req.body = jsonutils.dumps(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app())
            self.assertEqual(res.status_int, 400)

    def test_initialize_connection_exception(self):
        with mock.patch.object(volume_api.API,
                               'initialize_connection') as init_conn:
            init_conn.side_effect = \
                exception.VolumeBackendAPIException(data=None)
            body = {'os-initialize_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/fake/volumes/1/action')
            req.method = "POST"
            req.body = jsonutils.dumps(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app())
            self.assertEqual(res.status_int, 500)

    def test_terminate_connection(self):
        with mock.patch.object(volume_api.API,
                               'terminate_connection') as terminate_conn:
            terminate_conn.return_value = {}
            body = {'os-terminate_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/fake/volumes/1/action')
            req.method = "POST"
            req.body = jsonutils.dumps(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app())
            self.assertEqual(res.status_int, 202)

    def test_terminate_connection_without_connector(self):
        with mock.patch.object(volume_api.API,
                               'terminate_connection') as terminate_conn:
            terminate_conn.return_value = {}
            body = {'os-terminate_connection': {}}
            req = webob.Request.blank('/v2/fake/volumes/1/action')
            req.method = "POST"
            req.body = jsonutils.dumps(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app())
            self.assertEqual(res.status_int, 400)

    def test_terminate_connection_with_exception(self):
        with mock.patch.object(volume_api.API,
                               'terminate_connection') as terminate_conn:
            terminate_conn.side_effect = \
                exception.VolumeBackendAPIException(data=None)
            body = {'os-terminate_connection': {'connector': 'fake'}}
            req = webob.Request.blank('/v2/fake/volumes/1/action')
            req.method = "POST"
            req.body = jsonutils.dumps(body)
            req.headers["content-type"] = "application/json"

            res = req.get_response(fakes.wsgi_app())
            self.assertEqual(res.status_int, 500)

    def test_attach_to_instance(self):
        body = {'os-attach': {'instance_uuid': 'fake',
                              'mountpoint': '/dev/vdc',
                              'mode': 'rw'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_attach_to_host(self):
        # using 'read-write' mode attach volume by default
        body = {'os-attach': {'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_attach_with_invalid_arguments(self):
        # Invalid request to attach volume an invalid target
        body = {'os-attach': {'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

        # Invalid request to attach volume to an instance and a host
        body = {'os-attach': {'instance_uuid': 'fake',
                              'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

        # Invalid request to attach volume with an invalid mode
        body = {'os-attach': {'instance_uuid': 'fake',
                              'mountpoint': '/dev/vdc',
                              'mode': 'rr'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)
        body = {'os-attach': {'host_name': 'fake_host',
                              'mountpoint': '/dev/vdc',
                              'mode': 'ww'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.headers["content-type"] = "application/json"
        req.body = jsonutils.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_begin_detaching(self):
        def fake_begin_detaching(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'begin_detaching',
                       fake_begin_detaching)

        body = {'os-begin_detaching': {'fake': 'fake'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_roll_detaching(self):
        def fake_roll_detaching(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'roll_detaching',
                       fake_roll_detaching)

        body = {'os-roll_detaching': {'fake': 'fake'}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_extend_volume(self):
        def fake_extend_volume(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'extend',
                       fake_extend_volume)

        body = {'os-extend': {'new_size': 5}}
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = "POST"
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"

        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 202)

    def test_update_readonly_flag(self):
        def fake_update_readonly_flag(*args, **kwargs):
            return {}
        self.stubs.Set(volume.API, 'update_readonly_flag',
                       fake_update_readonly_flag)

        def make_update_readonly_flag_test(self, readonly, return_code):
            body = {"os-update_readonly_flag": {"readonly": readonly}}
            if readonly is None:
                body = {"os-update_readonly_flag": {}}
            req = webob.Request.blank('/v2/fake/volumes/1/action')
            req.method = "POST"
            req.body = jsonutils.dumps(body)
            req.headers["content-type"] = "application/json"
            res = req.get_response(fakes.wsgi_app())
            self.assertEqual(res.status_int, return_code)

        make_update_readonly_flag_test(self, True, 202)
        make_update_readonly_flag_test(self, False, 202)
        make_update_readonly_flag_test(self, '1', 202)
        make_update_readonly_flag_test(self, '0', 202)
        make_update_readonly_flag_test(self, 'true', 202)
        make_update_readonly_flag_test(self, 'false', 202)
        make_update_readonly_flag_test(self, 'tt', 400)
        make_update_readonly_flag_test(self, 11, 400)
        make_update_readonly_flag_test(self, None, 400)


class VolumeRetypeActionsTest(VolumeActionsTest):
    def setUp(self):
        def get_vol_type(*args, **kwargs):
            d1 = {'id': 'fake', 'qos_specs_id': 'fakeqid1', 'extra_specs': {}}
            d2 = {'id': 'foo', 'qos_specs_id': 'fakeqid2', 'extra_specs': {}}
            return d1 if d1['id'] == args[1] else d2

        self.retype_patchers = {}
        self.retype_mocks = {}
        paths = ['cinder.volume.volume_types.get_volume_type',
                 'cinder.volume.volume_types.get_volume_type_by_name',
                 'cinder.volume.qos_specs.get_qos_specs',
                 'cinder.quota.QUOTAS.add_volume_type_opts',
                 'cinder.quota.QUOTAS.reserve']
        for path in paths:
            name = path.split('.')[-1]
            self.retype_patchers[name] = mock.patch(path)
            self.retype_mocks[name] = self.retype_patchers[name].start()
            self.addCleanup(self.retype_patchers[name].stop)

        self.retype_mocks['get_volume_type'].side_effect = get_vol_type
        self.retype_mocks['get_volume_type_by_name'].side_effect = get_vol_type
        self.retype_mocks['add_volume_type_opts'].return_value = None
        self.retype_mocks['reserve'].return_value = None

        super(VolumeRetypeActionsTest, self).setUp()

    def _retype_volume_exec(self, expected_status, new_type='foo'):
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        retype_body = {'new_type': new_type, 'migration_policy': 'never'}
        req.body = jsonutils.dumps({'os-retype': retype_body})
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, expected_status)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs')
    def test_retype_volume_success(self, _mock_get_qspecs):
        # Test that the retype API works for both available and in-use
        self._retype_volume_exec(202)
        self.mock_volume_get.return_value['status'] = 'in-use'
        specs = {'qos_specs': {'id': 'fakeqid1', 'consumer': 'back-end'}}
        _mock_get_qspecs.return_value = specs
        self._retype_volume_exec(202)

    def test_retype_volume_no_body(self):
        # Request with no body should fail
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        req.body = jsonutils.dumps({'os-retype': None})
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_retype_volume_bad_policy(self):
        # Request with invalid migration policy should fail
        req = webob.Request.blank('/v2/fake/volumes/1/action')
        req.method = 'POST'
        req.headers['content-type'] = 'application/json'
        retype_body = {'new_type': 'foo', 'migration_policy': 'invalid'}
        req.body = jsonutils.dumps({'os-retype': retype_body})
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_retype_volume_bad_status(self):
        # Should fail if volume does not have proper status
        self.mock_volume_get.return_value['status'] = 'error'
        self._retype_volume_exec(400)

    def test_retype_type_no_exist(self):
        # Should fail if new type does not exist
        exc = exception.VolumeTypeNotFound('exc')
        self.retype_mocks['get_volume_type'].side_effect = exc
        self._retype_volume_exec(404)

    def test_retype_same_type(self):
        # Should fail if new type and old type are the same
        self._retype_volume_exec(400, new_type='fake')

    def test_retype_over_quota(self):
        # Should fail if going over quota for new type
        exc = exception.OverQuota(overs=['gigabytes'],
                                  quotas={'gigabytes': 20},
                                  usages={'gigabytes': {'reserved': 5,
                                                        'in_use': 15}})
        self.retype_mocks['reserve'].side_effect = exc
        self._retype_volume_exec(413)

    @mock.patch('cinder.volume.qos_specs.get_qos_specs')
    def _retype_volume_diff_qos(self, vol_status, consumer, expected_status,
                                _mock_get_qspecs):
        def fake_get_qos(ctxt, qos_id):
            d1 = {'qos_specs': {'id': 'fakeqid1', 'consumer': consumer}}
            d2 = {'qos_specs': {'id': 'fakeqid2', 'consumer': consumer}}
            return d1 if d1['qos_specs']['id'] == qos_id else d2

        self.mock_volume_get.return_value['status'] = vol_status
        _mock_get_qspecs.side_effect = fake_get_qos
        self._retype_volume_exec(expected_status)

    def test_retype_volume_diff_qos_fe_in_use(self):
        # should fail if changing qos enforced by front-end for in-use volumes
        self._retype_volume_diff_qos('in-use', 'front-end', 400)

    def test_retype_volume_diff_qos_fe_available(self):
        # should NOT fail if changing qos enforced by FE for available volumes
        self._retype_volume_diff_qos('available', 'front-end', 202)

    def test_retype_volume_diff_qos_be(self):
        # should NOT fail if changing qos enforced by back-end
        self._retype_volume_diff_qos('available', 'back-end', 202)
        self._retype_volume_diff_qos('in-use', 'back-end', 202)


def stub_volume_get(self, context, volume_id):
    volume = stubs.stub_volume(volume_id)
    if volume_id == 5:
        volume['status'] = 'in-use'
    else:
        volume['status'] = 'available'
    return volume


def stub_upload_volume_to_image_service(self, context, volume, metadata,
                                        force):
    ret = {"id": volume['id'],
           "updated_at": datetime.datetime(1, 1, 1, 1, 1, 1),
           "status": 'uploading',
           "display_description": volume['display_description'],
           "size": volume['size'],
           "volume_type": volume['volume_type'],
           "image_id": 1,
           "container_format": 'bare',
           "disk_format": 'raw',
           "image_name": 'image_name'}
    return ret


class VolumeImageActionsTest(test.TestCase):
    def setUp(self):
        super(VolumeImageActionsTest, self).setUp()
        self.controller = volume_actions.VolumeActionsController()

        self.stubs.Set(volume_api.API, 'get', stub_volume_get)

    def test_copy_volume_to_image(self):
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        res_dict = self.controller._volume_upload_image(req, id, body)
        expected = {'os-volume_upload_image': {'id': id,
                    'updated_at': datetime.datetime(1, 1, 1, 1, 1, 1),
                    'status': 'uploading',
                    'display_description': 'displaydesc',
                    'size': 1,
                    'volume_type': {'name': 'vol_type_name'},
                    'image_id': 1,
                    'container_format': 'bare',
                    'disk_format': 'raw',
                    'image_name': 'image_name'}}
        self.assertDictMatch(res_dict, expected)

    def test_copy_volume_to_image_volumenotfound(self):
        def stub_volume_get_raise_exc(self, context, volume_id):
            raise exception.VolumeNotFound(volume_id=volume_id)

        self.stubs.Set(volume_api.API, 'get', stub_volume_get_raise_exc)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_invalidvolume(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                                      metadata, force):
            raise exception.InvalidVolume(reason='blah')
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_valueerror(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                                      metadata, force):
            raise ValueError
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_remoteerror(self):
        def stub_upload_volume_to_image_service_raise(self, context, volume,
                                                      metadata, force):
            raise messaging.RemoteError
        self.stubs.Set(volume_api.API,
                       "copy_volume_to_image",
                       stub_upload_volume_to_image_service_raise)

        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": 'image_name',
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)

    def test_volume_upload_image_typeerror(self):
        id = 1
        body = {"os-volume_upload_image_fake": "fake"}
        req = webob.Request.blank('/v2/tenant1/volumes/%s/action' % id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_volume_upload_image_without_type(self):
        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": None,
               "force": True}
        body = {"": vol}
        req = webob.Request.blank('/v2/tenant1/volumes/%s/action' % id)
        req.method = 'POST'
        req.headers['Content-Type'] = 'application/json'
        req.body = json.dumps(body)
        res = req.get_response(fakes.wsgi_app())
        self.assertEqual(res.status_int, 400)

    def test_extend_volume_valueerror(self):
        id = 1
        body = {'os-extend': {'new_size': 'fake'}}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._extend,
                          req,
                          id,
                          body)

    def test_copy_volume_to_image_notimagename(self):
        id = 1
        vol = {"container_format": 'bare',
               "disk_format": 'raw',
               "image_name": None,
               "force": True}
        body = {"os-volume_upload_image": vol}
        req = fakes.HTTPRequest.blank('/v2/tenant1/volumes/%s/action' % id)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._volume_upload_image,
                          req,
                          id,
                          body)
