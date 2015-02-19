# Copyright 2010 OpenStack Foundation
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

from xml.dom import minidom

import gettext
import mock
import webob.dec
import webob.exc

from cinder.api import common
from cinder.api.openstack import wsgi
from cinder import exception
from cinder.openstack.common import gettextutils
from cinder.openstack.common import jsonutils
from cinder import test


class TestFaults(test.TestCase):
    """Tests covering `cinder.api.openstack.faults:Fault` class."""

    def _prepare_xml(self, xml_string):
        """Remove characters from string which hinder XML equality testing."""
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault_json(self):
        """Test fault serialized to JSON via file-extension and/or header."""
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
            response = request.get_response(fault)

            expected = {
                "badRequest": {
                    "message": "scram",
                    "code": 400,
                },
            }
            actual = jsonutils.loads(response.body)

            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(expected, actual)

    def test_413_fault_json(self):
        """Test fault serialized to JSON via file-extension and/or header."""
        requests = [
            webob.Request.blank('/.json'),
            webob.Request.blank('/', headers={"Accept": "application/json"}),
        ]

        for request in requests:
            exc = webob.exc.HTTPRequestEntityTooLarge
            fault = wsgi.Fault(exc(explanation='sorry',
                                   headers={'Retry-After': 4}))
            response = request.get_response(fault)

            expected = {
                "overLimit": {
                    "message": "sorry",
                    "code": 413,
                    "retryAfter": 4,
                },
            }
            actual = jsonutils.loads(response.body)

            self.assertEqual(response.content_type, "application/json")
            self.assertEqual(expected, actual)

    def test_raise(self):
        """Ensure the ability to raise :class:`Fault` in WSGI-ified methods."""
        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPNotFound(explanation='whut?'))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/xml")
        self.assertEqual(resp.status_int, 404)
        self.assertIn('whut?', resp.body)

    def test_raise_403(self):
        """Ensure the ability to raise :class:`Fault` in WSGI-ified methods."""
        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPForbidden(explanation='whut?'))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/xml")
        self.assertEqual(resp.status_int, 403)
        self.assertNotIn('resizeNotAllowed', resp.body)
        self.assertIn('forbidden', resp.body)

    def test_raise_http_with_localized_explanation(self):
        params = ('blah', )
        expl = gettextutils.Message("String with params: %s" % params, 'test')

        def _mock_translation(msg, locale):
            return "Mensaje traducido"

        self.stubs.Set(gettextutils,
                       "translate", _mock_translation)

        @webob.dec.wsgify
        def raiser(req):
            raise wsgi.Fault(webob.exc.HTTPNotFound(explanation=expl))

        req = webob.Request.blank('/.xml')
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/xml")
        self.assertEqual(resp.status_int, 404)
        self.assertIn(("Mensaje traducido"), resp.body)
        self.stubs.UnsetAll()

    @mock.patch('cinder.openstack.common.gettextutils.gettext.translation')
    def test_raise_invalid_with_localized_explanation(self, mock_translation):
        msg_template = gettextutils.Message("Invalid input: %(reason)s", "")
        reason = gettextutils.Message("Value is invalid", "")

        class MockESTranslations(gettext.GNUTranslations):
            def ugettext(self, msgid):
                if "Invalid input" in msgid:
                    return "Entrada invalida: %(reason)s"
                elif "Value is invalid" in msgid:
                    return "El valor es invalido"
                return msgid

        def translation(domain, localedir=None, languages=None, fallback=None):
            return MockESTranslations()

        mock_translation.side_effect = translation

        @webob.dec.wsgify
        def raiser(req):
            class MyInvalidInput(exception.InvalidInput):
                message = msg_template

            ex = MyInvalidInput(reason=reason)
            raise wsgi.Fault(exception.ConvertedException(code=ex.code,
                                                          explanation=ex.msg))

        req = webob.Request.blank("/.json")
        resp = req.get_response(raiser)
        self.assertEqual(resp.content_type, "application/json")
        self.assertEqual(resp.status_int, 400)
        # This response was comprised of Message objects from two different
        # exceptions, here we are testing that both got translated
        self.assertIn("Entrada invalida: El valor es invalido", resp.body)

    def test_fault_has_status_int(self):
        """Ensure the status_int is set correctly on faults."""
        fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='what?'))
        self.assertEqual(fault.status_int, 400)

    def test_xml_serializer(self):
        """Ensure that a v1.1 request responds with a v1 xmlns."""
        request = webob.Request.blank('/v1',
                                      headers={"Accept": "application/xml"})

        fault = wsgi.Fault(webob.exc.HTTPBadRequest(explanation='scram'))
        response = request.get_response(fault)

        self.assertIn(common.XML_NS_V1, response.body)
        self.assertEqual(response.content_type, "application/xml")
        self.assertEqual(response.status_int, 400)


class FaultsXMLSerializationTestV11(test.TestCase):
    """Tests covering `cinder.api.openstack.faults:Fault` class."""

    def _prepare_xml(self, xml_string):
        xml_string = xml_string.replace("  ", "")
        xml_string = xml_string.replace("\n", "")
        xml_string = xml_string.replace("\t", "")
        return xml_string

    def test_400_fault(self):
        metadata = {'attributes': {"badRequest": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V1)

        fixture = {
            "badRequest": {
                "message": "scram",
                "code": 400,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <badRequest code="400" xmlns="%s">
                    <message>scram</message>
                </badRequest>
            """) % common.XML_NS_V1)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_413_fault(self):
        metadata = {'attributes': {"overLimit": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V1)

        fixture = {
            "overLimit": {
                "message": "sorry",
                "code": 413,
                "retryAfter": 4,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <overLimit code="413" xmlns="%s">
                    <message>sorry</message>
                    <retryAfter>4</retryAfter>
                </overLimit>
            """) % common.XML_NS_V1)

        self.assertEqual(expected.toxml(), actual.toxml())

    def test_404_fault(self):
        metadata = {'attributes': {"itemNotFound": 'code'}}
        serializer = wsgi.XMLDictSerializer(metadata=metadata,
                                            xmlns=common.XML_NS_V1)

        fixture = {
            "itemNotFound": {
                "message": "sorry",
                "code": 404,
            },
        }

        output = serializer.serialize(fixture)
        actual = minidom.parseString(self._prepare_xml(output))

        expected = minidom.parseString(self._prepare_xml("""
                <itemNotFound code="404" xmlns="%s">
                    <message>sorry</message>
                </itemNotFound>
            """) % common.XML_NS_V1)

        self.assertEqual(expected.toxml(), actual.toxml())
