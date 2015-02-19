# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""Unit tests for `nova.wsgi`."""

import os.path
import tempfile
import testtools

import eventlet
import eventlet.wsgi
import mock
import requests

import nova.exception
from nova import test
from nova.tests import utils
import nova.wsgi
from oslo.config import cfg
import urllib2
import webob

SSL_CERT_DIR = os.path.normpath(os.path.join(
                                os.path.dirname(os.path.abspath(__file__)),
                                'ssl_cert'))
CONF = cfg.CONF


class TestLoaderNothingExists(test.NoDBTestCase):
    """Loader tests where os.path.exists always returns False."""

    def setUp(self):
        super(TestLoaderNothingExists, self).setUp()
        self.stubs.Set(os.path, 'exists', lambda _: False)

    def test_relpath_config_not_found(self):
        self.flags(api_paste_config='api-paste.ini')
        self.assertRaises(
            nova.exception.ConfigNotFound,
            nova.wsgi.Loader,
        )

    def test_asbpath_config_not_found(self):
        self.flags(api_paste_config='/etc/nova/api-paste.ini')
        self.assertRaises(
            nova.exception.ConfigNotFound,
            nova.wsgi.Loader,
        )


class TestLoaderNormalFilesystem(test.NoDBTestCase):
    """Loader tests with normal filesystem (unmodified os.path module)."""

    _paste_config = """
[app:test_app]
use = egg:Paste#static
document_root = /tmp
    """

    def setUp(self):
        super(TestLoaderNormalFilesystem, self).setUp()
        self.config = tempfile.NamedTemporaryFile(mode="w+t")
        self.config.write(self._paste_config.lstrip())
        self.config.seek(0)
        self.config.flush()
        self.loader = nova.wsgi.Loader(self.config.name)

    def test_config_found(self):
        self.assertEqual(self.config.name, self.loader.config_path)

    def test_app_not_found(self):
        self.assertRaises(
            nova.exception.PasteAppNotFound,
            self.loader.load_app,
            "nonexistent app",
        )

    def test_app_found(self):
        url_parser = self.loader.load_app("test_app")
        self.assertEqual("/tmp", url_parser.directory)

    def tearDown(self):
        self.config.close()
        super(TestLoaderNormalFilesystem, self).tearDown()


class TestWSGIServer(test.NoDBTestCase):
    """WSGI server tests."""

    def test_no_app(self):
        server = nova.wsgi.Server("test_app", None)
        self.assertEqual("test_app", server.name)

    def test_custom_max_header_line(self):
        CONF.max_header_line = 4096  # Default value is 16384.
        server = nova.wsgi.Server("test_custom_max_header_line", None)
        self.assertEqual(CONF.max_header_line, eventlet.wsgi.MAX_HEADER_LINE)

    def test_start_random_port(self):
        server = nova.wsgi.Server("test_random_port", None,
                                  host="127.0.0.1", port=0)
        server.start()
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    @testtools.skipIf(not utils.is_ipv6_supported(), "no ipv6 support")
    def test_start_random_port_with_ipv6(self):
        server = nova.wsgi.Server("test_random_port", None,
            host="::1", port=0)
        server.start()
        self.assertEqual("::1", server.host)
        self.assertNotEqual(0, server.port)
        server.stop()
        server.wait()

    def test_server_pool_waitall(self):
        # test pools waitall method gets called while stopping server
        server = nova.wsgi.Server("test_server", None,
            host="127.0.0.1", port=4444)
        server.start()
        with mock.patch.object(server._pool,
                              'waitall') as mock_waitall:
            server.stop()
            server.wait()
            mock_waitall.assert_called_once_with()

    def test_uri_length_limit(self):
        server = nova.wsgi.Server("test_uri_length_limit", None,
            host="127.0.0.1", max_url_len=16384)
        server.start()

        uri = "http://127.0.0.1:%d/%s" % (server.port, 10000 * 'x')
        resp = requests.get(uri)
        eventlet.sleep(0)
        self.assertNotEqual(resp.status_code,
                            requests.codes.REQUEST_URI_TOO_LARGE)

        uri = "http://127.0.0.1:%d/%s" % (server.port, 20000 * 'x')
        resp = requests.get(uri)
        eventlet.sleep(0)
        self.assertEqual(resp.status_code,
                         requests.codes.REQUEST_URI_TOO_LARGE)
        server.stop()
        server.wait()


class TestWSGIServerWithSSL(test.NoDBTestCase):
    """WSGI server with SSL tests."""

    def setUp(self):
        super(TestWSGIServerWithSSL, self).setUp()
        self.flags(enabled_ssl_apis=['fake_ssl'],
                ssl_cert_file=os.path.join(SSL_CERT_DIR, 'certificate.crt'),
                ssl_key_file=os.path.join(SSL_CERT_DIR, 'privatekey.key'))

    def test_ssl_server(self):

        def test_app(env, start_response):
            start_response('200 OK', {})
            return ['PONG']

        fake_ssl_server = nova.wsgi.Server("fake_ssl", test_app,
                                           host="127.0.0.1", port=0,
                                           use_ssl=True)
        fake_ssl_server.start()
        self.assertNotEqual(0, fake_ssl_server.port)

        cli = eventlet.connect(("localhost", fake_ssl_server.port))
        cli = eventlet.wrap_ssl(cli,
                                ca_certs=os.path.join(SSL_CERT_DIR, 'ca.crt'))

        cli.write('POST / HTTP/1.1\r\nHost: localhost\r\n'
                  'Connection: close\r\nContent-length:4\r\n\r\nPING')
        response = cli.read(8192)
        self.assertEqual(response[-4:], "PONG")

        fake_ssl_server.stop()
        fake_ssl_server.wait()

    def test_two_servers(self):

        def test_app(env, start_response):
            start_response('200 OK', {})
            return ['PONG']

        fake_ssl_server = nova.wsgi.Server("fake_ssl", test_app,
            host="127.0.0.1", port=0, use_ssl=True)
        fake_ssl_server.start()
        self.assertNotEqual(0, fake_ssl_server.port)

        fake_server = nova.wsgi.Server("fake", test_app,
            host="127.0.0.1", port=0)
        fake_server.start()
        self.assertNotEqual(0, fake_server.port)

        cli = eventlet.connect(("localhost", fake_ssl_server.port))
        cli = eventlet.wrap_ssl(cli,
                                ca_certs=os.path.join(SSL_CERT_DIR, 'ca.crt'))

        cli.write('POST / HTTP/1.1\r\nHost: localhost\r\n'
                  'Connection: close\r\nContent-length:4\r\n\r\nPING')
        response = cli.read(8192)
        self.assertEqual(response[-4:], "PONG")

        cli = eventlet.connect(("localhost", fake_server.port))

        cli.sendall('POST / HTTP/1.1\r\nHost: localhost\r\n'
                  'Connection: close\r\nContent-length:4\r\n\r\nPING')
        response = cli.recv(8192)
        self.assertEqual(response[-4:], "PONG")

        fake_ssl_server.stop()
        fake_ssl_server.wait()

    @testtools.skipIf(not utils.is_ipv6_supported(), "no ipv6 support")
    def test_app_using_ipv6_and_ssl(self):
        greetings = 'Hello, World!!!'

        @webob.dec.wsgify
        def hello_world(req):
            return greetings

        server = nova.wsgi.Server("fake_ssl",
                                  hello_world,
                                  host="::1",
                                  port=0,
                                  use_ssl=True)

        server.start()

        response = urllib2.urlopen('https://[::1]:%d/' % server.port)
        self.assertEqual(greetings, response.read())

        server.stop()
        server.wait()
