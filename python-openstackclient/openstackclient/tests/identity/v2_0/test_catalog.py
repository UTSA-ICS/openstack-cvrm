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

from openstackclient.identity.v2_0 import catalog
from openstackclient.tests import utils


class TestCatalog(utils.TestCommand):

    fake_service = {
        'id': 'qwertyuiop',
        'type': 'compute',
        'name': 'supernova',
        'endpoints': [{
            'region': 'onlyone',
            'publicURL': 'https://public.example.com',
            'adminURL': 'https://admin.example.com',
        }],
    }

    def setUp(self):
        super(TestCatalog, self).setUp()

        self.sc_mock = mock.MagicMock()
        self.sc_mock.service_catalog.get_data.return_value = [
            self.fake_service,
        ]

        self.auth_mock = mock.MagicMock()
        self.app.client_manager.session = self.auth_mock

        self.auth_mock.auth.get_auth_ref.return_value = self.sc_mock


class TestCatalogList(TestCatalog):

    def setUp(self):
        super(TestCatalogList, self).setUp()

        # Get the command object to test
        self.cmd = catalog.ListCatalog(self.app, None)

    def test_catalog_list(self):
        arglist = []
        verifylist = []
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)

        # DisplayCommandBase.take_action() returns two tuples
        columns, data = self.cmd.take_action(parsed_args)
        self.sc_mock.service_catalog.get_data.assert_called_with()

        collist = ('Name', 'Type', 'Endpoints')
        self.assertEqual(collist, columns)
        datalist = ((
            'supernova',
            'compute',
            'onlyone\n  publicURL: https://public.example.com\n  '
            'internalURL: https://public.example.com\n  '
            'adminURL: https://public.example.com\n',
        ), )
        self.assertEqual(datalist, tuple(data))


class TestCatalogShow(TestCatalog):

    def setUp(self):
        super(TestCatalogShow, self).setUp()

        # Get the command object to test
        self.cmd = catalog.ShowCatalog(self.app, None)

    def test_catalog_show(self):
        arglist = [
            'compute',
        ]
        verifylist = [
            ('service', 'compute'),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)

        # DisplayCommandBase.take_action() returns two tuples
        columns, data = self.cmd.take_action(parsed_args)
        self.sc_mock.service_catalog.get_data.assert_called_with()

        collist = ('endpoints', 'id', 'name', 'type')
        self.assertEqual(collist, columns)
        datalist = (
            'onlyone\n  publicURL: https://public.example.com\n  '
            'internalURL: https://public.example.com\n  '
            'adminURL: https://public.example.com\n',
            'qwertyuiop',
            'supernova',
            'compute',
        )
        self.assertEqual(datalist, data)
