#   Copyright 2012-2013 OpenStack Foundation
#
#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#
import mock
from requests_mock.contrib import fixture

from keystoneclient.auth.identity import v2 as auth_v2
from keystoneclient import service_catalog
from oslo.serialization import jsonutils

from openstackclient.api import auth
from openstackclient.common import clientmanager
from openstackclient.common import exceptions as exc
from openstackclient.tests import fakes
from openstackclient.tests import utils


API_VERSION = {"identity": "2.0"}

AUTH_REF = {'version': 'v2.0'}
AUTH_REF.update(fakes.TEST_RESPONSE_DICT['access'])
SERVICE_CATALOG = service_catalog.ServiceCatalogV2(AUTH_REF)


class Container(object):
    attr = clientmanager.ClientCache(lambda x: object())

    def __init__(self):
        pass


class FakeOptions(object):
    def __init__(self, **kwargs):
        for option in auth.OPTIONS_LIST:
            setattr(self, 'os_' + option.replace('-', '_'), None)
        self.os_auth_type = None
        self.os_identity_api_version = '2.0'
        self.timing = None
        self.os_region_name = None
        self.os_url = None
        self.__dict__.update(kwargs)


class TestClientCache(utils.TestCase):

    def test_singleton(self):
        # NOTE(dtroyer): Verify that the ClientCache descriptor only invokes
        # the factory one time and always returns the same value after that.
        c = Container()
        self.assertEqual(c.attr, c.attr)


class TestClientManager(utils.TestCase):
    def setUp(self):
        super(TestClientManager, self).setUp()
        self.mock = mock.Mock()
        self.requests = self.useFixture(fixture.Fixture())
        # fake v2password token retrieval
        self.stub_auth(json=fakes.TEST_RESPONSE_DICT)
        # fake v3password token retrieval
        self.stub_auth(json=fakes.TEST_RESPONSE_DICT_V3,
                       url='/'.join([fakes.AUTH_URL, 'auth/tokens']))
        # fake password version endpoint discovery
        self.stub_auth(json=fakes.TEST_VERSIONS,
                       url=fakes.AUTH_URL,
                       verb='GET')

    def test_client_manager_token_endpoint(self):

        client_manager = clientmanager.ClientManager(
            auth_options=FakeOptions(os_token=fakes.AUTH_TOKEN,
                                     os_url=fakes.AUTH_URL,
                                     os_auth_type='token_endpoint'),
            api_version=API_VERSION,
            verify=True
        )
        self.assertEqual(
            fakes.AUTH_URL,
            client_manager._url,
        )
        self.assertEqual(
            fakes.AUTH_TOKEN,
            client_manager.auth.get_token(None),
        )
        self.assertIsInstance(
            client_manager.auth,
            auth.TokenEndpoint,
        )
        self.assertFalse(client_manager._insecure)
        self.assertTrue(client_manager._verify)

    def test_client_manager_token(self):

        client_manager = clientmanager.ClientManager(
            auth_options=FakeOptions(os_token=fakes.AUTH_TOKEN,
                                     os_auth_url=fakes.AUTH_URL,
                                     os_auth_type='v2token'),
            api_version=API_VERSION,
            verify=True
        )

        self.assertEqual(
            fakes.AUTH_URL,
            client_manager._auth_url,
        )
        self.assertIsInstance(
            client_manager.auth,
            auth_v2.Token,
        )
        self.assertFalse(client_manager._insecure)
        self.assertTrue(client_manager._verify)

    def test_client_manager_password(self):

        client_manager = clientmanager.ClientManager(
            auth_options=FakeOptions(os_auth_url=fakes.AUTH_URL,
                                     os_username=fakes.USERNAME,
                                     os_password=fakes.PASSWORD),
            api_version=API_VERSION,
            verify=False,
        )

        self.assertEqual(
            fakes.AUTH_URL,
            client_manager._auth_url,
        )
        self.assertEqual(
            fakes.USERNAME,
            client_manager._username,
        )
        self.assertEqual(
            fakes.PASSWORD,
            client_manager._password,
        )
        self.assertIsInstance(
            client_manager.auth,
            auth_v2.Password,
        )
        self.assertTrue(client_manager._insecure)
        self.assertFalse(client_manager._verify)

        # These need to stick around until the old-style clients are gone
        self.assertEqual(
            AUTH_REF,
            client_manager.auth_ref,
        )
        self.assertEqual(
            dir(SERVICE_CATALOG),
            dir(client_manager.auth_ref.service_catalog),
        )

    def stub_auth(self, json=None, url=None, verb=None, **kwargs):
        subject_token = fakes.AUTH_TOKEN
        base_url = fakes.AUTH_URL
        if json:
            text = jsonutils.dumps(json)
            headers = {'X-Subject-Token': subject_token,
                       'Content-Type': 'application/json'}
        if not url:
            url = '/'.join([base_url, 'tokens'])
        url = url.replace("/?", "?")
        if not verb:
            verb = 'POST'
        self.requests.register_uri(verb,
                                   url,
                                   headers=headers,
                                   text=text)

    def test_client_manager_password_verify_ca(self):

        client_manager = clientmanager.ClientManager(
            auth_options=FakeOptions(os_auth_url=fakes.AUTH_URL,
                                     os_username=fakes.USERNAME,
                                     os_password=fakes.PASSWORD,
                                     os_auth_type='v2password'),
            api_version=API_VERSION,
            verify='cafile',
        )

        self.assertFalse(client_manager._insecure)
        self.assertTrue(client_manager._verify)
        self.assertEqual('cafile', client_manager._cacert)

    def _select_auth_plugin(self, auth_params, api_version, auth_plugin_name):
        auth_params['os_auth_type'] = auth_plugin_name
        auth_params['os_identity_api_version'] = api_version
        client_manager = clientmanager.ClientManager(
            auth_options=FakeOptions(**auth_params),
            api_version=API_VERSION,
            verify=True
        )
        self.assertEqual(
            auth_plugin_name,
            client_manager.auth_plugin_name,
        )

    def test_client_manager_select_auth_plugin(self):
        # test token auth
        params = dict(os_token=fakes.AUTH_TOKEN,
                      os_auth_url=fakes.AUTH_URL)
        self._select_auth_plugin(params, '2.0', 'v2token')
        self._select_auth_plugin(params, '3', 'v3token')
        self._select_auth_plugin(params, 'XXX', 'token')
        # test token/endpoint auth
        params = dict(os_token=fakes.AUTH_TOKEN, os_url='test')
        self._select_auth_plugin(params, 'XXX', 'token_endpoint')
        # test password auth
        params = dict(os_auth_url=fakes.AUTH_URL,
                      os_username=fakes.USERNAME,
                      os_password=fakes.PASSWORD)
        self._select_auth_plugin(params, '2.0', 'v2password')
        self._select_auth_plugin(params, '3', 'v3password')
        self._select_auth_plugin(params, 'XXX', 'password')

    def test_client_manager_select_auth_plugin_failure(self):
        self.assertRaises(exc.CommandError,
                          clientmanager.ClientManager,
                          auth_options=FakeOptions(os_auth_plugin=''),
                          api_version=API_VERSION,
                          verify=True)
