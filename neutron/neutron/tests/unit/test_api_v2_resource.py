# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 Intel Corporation.
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
#
# @author: Zhongyue Luo, Intel Corporation.
#

import mock
from webob import exc
import webtest

from neutron.api.v2 import resource as wsgi_resource
from neutron.common import exceptions as n_exc
from neutron import context
from neutron.openstack.common import gettextutils
from neutron.tests import base
from neutron import wsgi


class RequestTestCase(base.BaseTestCase):
    def setUp(self):
        super(RequestTestCase, self).setUp()
        self.req = wsgi_resource.Request({'foo': 'bar'})

    def test_content_type_missing(self):
        request = wsgi.Request.blank('/tests/123', method='POST')
        request.body = "<body />"
        self.assertIsNone(request.get_content_type())

    def test_content_type_with_charset(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Content-Type"] = "application/json; charset=UTF-8"
        result = request.get_content_type()
        self.assertEqual(result, "application/json")

    def test_content_type_from_accept(self):
        for content_type in ('application/xml',
                             'application/json'):
            request = wsgi.Request.blank('/tests/123')
            request.headers["Accept"] = content_type
            result = request.best_match_content_type()
            self.assertEqual(result, content_type)

    def test_content_type_from_accept_best(self):
        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = "application/xml, application/json"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

        request = wsgi.Request.blank('/tests/123')
        request.headers["Accept"] = ("application/json; q=0.3, "
                                     "application/xml; q=0.9")
        result = request.best_match_content_type()
        self.assertEqual(result, "application/xml")

    def test_content_type_from_query_extension(self):
        request = wsgi.Request.blank('/tests/123.xml')
        result = request.best_match_content_type()
        self.assertEqual(result, "application/xml")

        request = wsgi.Request.blank('/tests/123.json')
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

        request = wsgi.Request.blank('/tests/123.invalid')
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

    def test_content_type_accept_and_query_extension(self):
        request = wsgi.Request.blank('/tests/123.xml')
        request.headers["Accept"] = "application/json"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/xml")

    def test_content_type_accept_default(self):
        request = wsgi.Request.blank('/tests/123.unsupported')
        request.headers["Accept"] = "application/unsupported1"
        result = request.best_match_content_type()
        self.assertEqual(result, "application/json")

    def test_context_with_neutron_context(self):
        ctxt = context.Context('fake_user', 'fake_tenant')
        self.req.environ['neutron.context'] = ctxt
        self.assertEqual(self.req.context, ctxt)

    def test_context_without_neutron_context(self):
        self.assertTrue(self.req.context.is_admin)

    def test_best_match_language(self):
        # Test that we are actually invoking language negotiation by webop
        request = wsgi.Request.blank('/')
        gettextutils.get_available_languages = mock.MagicMock()
        gettextutils.get_available_languages.return_value = ['known-language',
                                                             'es', 'zh']
        request.headers['Accept-Language'] = 'known-language'
        language = request.best_match_language()
        self.assertEqual(language, 'known-language')

        # If the Accept-Leader is an unknown language, missing or empty,
        # the best match locale should be None
        request.headers['Accept-Language'] = 'unknown-language'
        language = request.best_match_language()
        self.assertIsNone(language)
        request.headers['Accept-Language'] = ''
        language = request.best_match_language()
        self.assertIsNone(language)
        request.headers.pop('Accept-Language')
        language = request.best_match_language()
        self.assertIsNone(language)


class ResourceTestCase(base.BaseTestCase):

    def test_unmapped_neutron_error_with_json(self):
        msg = u'\u7f51\u7edc'

        class TestException(n_exc.NeutronException):
            message = msg
        expected_res = {'body': {
            'NeutronError': {
                'type': 'TestException',
                'message': msg,
                'detail': ''}}}
        controller = mock.MagicMock()
        controller.test.side_effect = TestException()

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'json'})}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPInternalServerError.code)
        self.assertEqual(wsgi.JSONDeserializer().deserialize(res.body),
                         expected_res)

    def test_unmapped_neutron_error_with_xml(self):
        msg = u'\u7f51\u7edc'

        class TestException(n_exc.NeutronException):
            message = msg
        expected_res = {'body': {
            'NeutronError': {
                'type': 'TestException',
                'message': msg,
                'detail': ''}}}
        controller = mock.MagicMock()
        controller.test.side_effect = TestException()

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'xml'})}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPInternalServerError.code)
        self.assertEqual(wsgi.XMLDeserializer().deserialize(res.body),
                         expected_res)

    @mock.patch('neutron.openstack.common.gettextutils.translate')
    def test_unmapped_neutron_error_localized(self, mock_translation):
        gettextutils.install('blaa', lazy=True)
        msg_translation = 'Translated error'
        mock_translation.return_value = msg_translation
        msg = _('Unmapped error')

        class TestException(n_exc.NeutronException):
            message = msg

        controller = mock.MagicMock()
        controller.test.side_effect = TestException()
        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'json'})}

        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPInternalServerError.code)
        self.assertIn(msg_translation,
                      str(wsgi.JSONDeserializer().deserialize(res.body)))

    def test_mapped_neutron_error_with_json(self):
        msg = u'\u7f51\u7edc'

        class TestException(n_exc.NeutronException):
            message = msg
        expected_res = {'body': {
            'NeutronError': {
                'type': 'TestException',
                'message': msg,
                'detail': ''}}}
        controller = mock.MagicMock()
        controller.test.side_effect = TestException()

        faults = {TestException: exc.HTTPGatewayTimeout}
        resource = webtest.TestApp(wsgi_resource.Resource(controller,
                                                          faults=faults))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'json'})}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPGatewayTimeout.code)
        self.assertEqual(wsgi.JSONDeserializer().deserialize(res.body),
                         expected_res)

    def test_mapped_neutron_error_with_xml(self):
        msg = u'\u7f51\u7edc'

        class TestException(n_exc.NeutronException):
            message = msg
        expected_res = {'body': {
            'NeutronError': {
                'type': 'TestException',
                'message': msg,
                'detail': ''}}}
        controller = mock.MagicMock()
        controller.test.side_effect = TestException()

        faults = {TestException: exc.HTTPGatewayTimeout}
        resource = webtest.TestApp(wsgi_resource.Resource(controller,
                                                          faults=faults))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'xml'})}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPGatewayTimeout.code)
        self.assertEqual(wsgi.XMLDeserializer().deserialize(res.body),
                         expected_res)

    @mock.patch('neutron.openstack.common.gettextutils.translate')
    def test_mapped_neutron_error_localized(self, mock_translation):
        gettextutils.install('blaa', lazy=True)
        msg_translation = 'Translated error'
        mock_translation.return_value = msg_translation
        msg = _('Unmapped error')

        class TestException(n_exc.NeutronException):
            message = msg

        controller = mock.MagicMock()
        controller.test.side_effect = TestException()
        faults = {TestException: exc.HTTPGatewayTimeout}
        resource = webtest.TestApp(wsgi_resource.Resource(controller,
                                                          faults=faults))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'json'})}

        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPGatewayTimeout.code)
        self.assertIn(msg_translation,
                      str(wsgi.JSONDeserializer().deserialize(res.body)))

    def test_http_error(self):
        controller = mock.MagicMock()
        controller.test.side_effect = exc.HTTPGatewayTimeout()

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test'})}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPGatewayTimeout.code)

    def test_unhandled_error_with_json(self):
        expected_res = {'body': {'NeutronError':
                                 _('Request Failed: internal server error '
                                   'while processing your request.')}}
        controller = mock.MagicMock()
        controller.test.side_effect = Exception()

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'json'})}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPInternalServerError.code)
        self.assertEqual(wsgi.JSONDeserializer().deserialize(res.body),
                         expected_res)

    def test_unhandled_error_with_xml(self):
        expected_res = {'body': {'NeutronError':
                                 _('Request Failed: internal server error '
                                   'while processing your request.')}}
        controller = mock.MagicMock()
        controller.test.side_effect = Exception()

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test',
                                                   'format': 'xml'})}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPInternalServerError.code)
        self.assertEqual(wsgi.XMLDeserializer().deserialize(res.body),
                         expected_res)

    def test_status_200(self):
        controller = mock.MagicMock()
        controller.test = lambda request: {'foo': 'bar'}

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test'})}
        res = resource.get('', extra_environ=environ)
        self.assertEqual(res.status_int, 200)

    def test_status_204(self):
        controller = mock.MagicMock()
        controller.test = lambda request: {'foo': 'bar'}

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'delete'})}
        res = resource.delete('', extra_environ=environ)
        self.assertEqual(res.status_int, 204)

    def _test_error_log_level(self, map_webob_exc, expect_log_info=False,
                              use_fault_map=True):
        class TestException(n_exc.NeutronException):
            message = 'Test Exception'

        controller = mock.MagicMock()
        controller.test.side_effect = TestException()
        faults = {TestException: map_webob_exc} if use_fault_map else {}
        resource = webtest.TestApp(wsgi_resource.Resource(controller, faults))
        environ = {'wsgiorg.routing_args': (None, {'action': 'test'})}
        with mock.patch.object(wsgi_resource, 'LOG') as log:
            res = resource.get('', extra_environ=environ, expect_errors=True)
            self.assertEqual(res.status_int, map_webob_exc.code)
        self.assertEqual(expect_log_info, log.info.called)
        self.assertNotEqual(expect_log_info, log.exception.called)

    def test_4xx_error_logged_info_level(self):
        self._test_error_log_level(exc.HTTPNotFound, expect_log_info=True)

    def test_non_4xx_error_logged_exception_level(self):
        self._test_error_log_level(exc.HTTPServiceUnavailable,
                                   expect_log_info=False)

    def test_unmapped_error_logged_exception_level(self):
        self._test_error_log_level(exc.HTTPInternalServerError,
                                   expect_log_info=False, use_fault_map=False)

    def test_no_route_args(self):
        controller = mock.MagicMock()

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {}
        res = resource.get('', extra_environ=environ, expect_errors=True)
        self.assertEqual(res.status_int, exc.HTTPInternalServerError.code)

    def test_post_with_body(self):
        controller = mock.MagicMock()
        controller.test = lambda request, body: {'foo': 'bar'}

        resource = webtest.TestApp(wsgi_resource.Resource(controller))

        environ = {'wsgiorg.routing_args': (None, {'action': 'test'})}
        res = resource.post('', params='{"key": "val"}',
                            extra_environ=environ)
        self.assertEqual(res.status_int, 200)
