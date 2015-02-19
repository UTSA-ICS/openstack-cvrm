# Copyright (c) 2010-2012 OpenStack, LLC.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.
from requests import RequestException
from time import sleep
import testtools
from six.moves import reload_module
from swiftclient import client as c


def fake_get_auth_keystone(os_options, exc=None, **kwargs):
    def fake_get_auth_keystone(auth_url,
                               user,
                               key,
                               actual_os_options, **actual_kwargs):
        if exc:
            raise exc('test')
        if actual_os_options != os_options:
            return "", None

        if auth_url.startswith("https") and \
           auth_url.endswith("invalid-certificate") and \
           not actual_kwargs['insecure']:
            from swiftclient import client as c
            raise c.ClientException("invalid-certificate")
        if auth_url.startswith("https") and \
           auth_url.endswith("self-signed-certificate") and \
           not actual_kwargs['insecure'] and \
           actual_kwargs['cacert'] is None:
            from swiftclient import client as c
            raise c.ClientException("unverified-certificate")
        if 'required_kwargs' in kwargs:
            for k, v in kwargs['required_kwargs'].items():
                if v != actual_kwargs.get(k):
                    return "", None

        return "http://url/", "token"
    return fake_get_auth_keystone


def fake_http_connect(*code_iter, **kwargs):

    class FakeConn(object):

        def __init__(self, status, etag=None, body='', timestamp='1'):
            self.status = status
            self.reason = 'Fake'
            self.host = '1.2.3.4'
            self.port = '1234'
            self.sent = 0
            self.received = 0
            self.etag = etag
            self.body = body
            self.timestamp = timestamp
            self._is_closed = True

        def connect(self):
            self._is_closed = False

        def close(self):
            self._is_closed = True

        def isclosed(self):
            return self._is_closed

        def getresponse(self):
            if kwargs.get('raise_exc'):
                raise Exception('test')
            return self

        def getexpect(self):
            if self.status == -2:
                raise RequestException()
            if self.status == -3:
                return FakeConn(507)
            return FakeConn(100)

        def getheaders(self):
            headers = {'content-length': len(self.body),
                       'content-type': 'x-application/test',
                       'x-timestamp': self.timestamp,
                       'last-modified': self.timestamp,
                       'x-object-meta-test': 'testing',
                       'etag':
                       self.etag or '"68b329da9893e34099c7d8ad5cb9c940"',
                       'x-works': 'yes',
                       'x-account-container-count': 12345}
            if not self.timestamp:
                del headers['x-timestamp']
            try:
                if next(container_ts_iter) is False:
                    headers['x-container-timestamp'] = '1'
            except StopIteration:
                pass
            if 'slow' in kwargs:
                headers['content-length'] = '4'
            if 'headers' in kwargs:
                headers.update(kwargs['headers'])
            if 'auth_v1' in kwargs:
                headers.update(
                    {'x-storage-url': 'storageURL',
                     'x-auth-token': 'someauthtoken'})
            return headers.items()

        def read(self, amt=None):
            if 'slow' in kwargs:
                if self.sent < 4:
                    self.sent += 1
                    sleep(0.1)
                    return ' '
            rv = self.body[:amt]
            self.body = self.body[amt:]
            return rv

        def send(self, amt=None):
            if 'slow' in kwargs:
                if self.received < 4:
                    self.received += 1
                    sleep(0.1)

        def getheader(self, name, default=None):
            return dict(self.getheaders()).get(name.lower(), default)

    timestamps_iter = iter(kwargs.get('timestamps') or ['1'] * len(code_iter))
    etag_iter = iter(kwargs.get('etags') or [None] * len(code_iter))
    x = kwargs.get('missing_container', [False] * len(code_iter))
    if not isinstance(x, (tuple, list)):
        x = [x] * len(code_iter)
    container_ts_iter = iter(x)
    code_iter = iter(code_iter)

    def connect(*args, **ckwargs):
        if 'give_content_type' in kwargs:
            if len(args) >= 7 and 'Content-Type' in args[6]:
                kwargs['give_content_type'](args[6]['Content-Type'])
            else:
                kwargs['give_content_type']('')
        if 'give_connect' in kwargs:
            kwargs['give_connect'](*args, **ckwargs)
        status = next(code_iter)
        etag = next(etag_iter)
        timestamp = next(timestamps_iter)
        if status <= 0:
            raise RequestException()
        fake_conn = FakeConn(status, etag, body=kwargs.get('body', ''),
                             timestamp=timestamp)
        fake_conn.connect()
        return fake_conn

    return connect


class MockHttpTest(testtools.TestCase):

    def setUp(self):
        super(MockHttpTest, self).setUp()

        def fake_http_connection(*args, **kwargs):
            _orig_http_connection = c.http_connection
            return_read = kwargs.get('return_read')
            query_string = kwargs.get('query_string')
            storage_url = kwargs.get('storage_url')
            auth_token = kwargs.get('auth_token')
            exc = kwargs.get('exc')

            def wrapper(url, proxy=None, cacert=None, insecure=False,
                        ssl_compression=True):
                if storage_url:
                    self.assertEqual(storage_url, url)

                parsed, _conn = _orig_http_connection(url, proxy=proxy)
                conn = fake_http_connect(*args, **kwargs)()

                def request(method, url, *args, **kwargs):
                    if auth_token:
                        headers = args[1]
                        self.assertTrue('X-Auth-Token' in headers)
                        actual_token = headers.get('X-Auth-Token')
                        self.assertEqual(auth_token, actual_token)
                    if query_string:
                        self.assertTrue(url.endswith('?' + query_string))
                    if url.endswith('invalid_cert') and not insecure:
                        from swiftclient import client as c
                        raise c.ClientException("invalid_certificate")
                    elif exc:
                        raise exc
                    return
                conn.request = request

                conn.has_been_read = False
                _orig_read = conn.read

                def read(*args, **kwargs):
                    conn.has_been_read = True
                    return _orig_read(*args, **kwargs)
                conn.read = return_read or read

                return parsed, conn
            return wrapper
        self.fake_http_connection = fake_http_connection

    def tearDown(self):
        super(MockHttpTest, self).tearDown()
        reload_module(c)
