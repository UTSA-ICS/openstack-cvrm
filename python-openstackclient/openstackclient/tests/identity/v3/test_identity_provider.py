#   Copyright 2014 CERN.
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

import copy

from openstackclient.identity.v3 import identity_provider
from openstackclient.tests import fakes
from openstackclient.tests.identity.v3 import fakes as identity_fakes


class TestIdentityProvider(identity_fakes.TestFederatedIdentity):

    def setUp(self):
        super(TestIdentityProvider, self).setUp()

        federation_lib = self.app.client_manager.identity.federation
        self.identity_providers_mock = federation_lib.identity_providers
        self.identity_providers_mock.reset_mock()


class TestIdentityProviderCreate(TestIdentityProvider):

    def setUp(self):
        super(TestIdentityProviderCreate, self).setUp()

        copied_idp = copy.deepcopy(identity_fakes.IDENTITY_PROVIDER)
        resource = fakes.FakeResource(None, copied_idp, loaded=True)
        self.identity_providers_mock.create.return_value = resource
        self.cmd = identity_provider.CreateIdentityProvider(self.app, None)

    def test_create_identity_provider_no_options(self):
        arglist = [
            identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider_id', identity_fakes.idp_id),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)
        columns, data = self.cmd.take_action(parsed_args)

        # Set expected values
        kwargs = {
            'enabled': True,
            'description': None,
        }

        self.identity_providers_mock.create.assert_called_with(
            id=identity_fakes.idp_id,
            **kwargs
        )

        collist = ('description', 'enabled', 'id')
        self.assertEqual(columns, collist)
        datalist = (
            identity_fakes.idp_description,
            True,
            identity_fakes.idp_id,
        )
        self.assertEqual(data, datalist)

    def test_create_identity_provider_description(self):
        arglist = [
            '--description', identity_fakes.idp_description,
            identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider_id', identity_fakes.idp_id),
            ('description', identity_fakes.idp_description),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)
        columns, data = self.cmd.take_action(parsed_args)

        # Set expected values
        kwargs = {
            'description': identity_fakes.idp_description,
            'enabled': True,
        }

        self.identity_providers_mock.create.assert_called_with(
            id=identity_fakes.idp_id,
            **kwargs
        )

        collist = ('description', 'enabled', 'id')
        self.assertEqual(columns, collist)
        datalist = (
            identity_fakes.idp_description,
            True,
            identity_fakes.idp_id,
        )
        self.assertEqual(data, datalist)

    def test_create_identity_provider_disabled(self):

        # Prepare FakeResource object
        IDENTITY_PROVIDER = copy.deepcopy(identity_fakes.IDENTITY_PROVIDER)
        IDENTITY_PROVIDER['enabled'] = False
        IDENTITY_PROVIDER['description'] = None

        resource = fakes.FakeResource(None, IDENTITY_PROVIDER, loaded=True)
        self.identity_providers_mock.create.return_value = resource

        arglist = [
            '--disable',
            identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider_id', identity_fakes.idp_id),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)
        columns, data = self.cmd.take_action(parsed_args)

        # Set expected values
        kwargs = {
            'enabled': False,
            'description': None,
        }

        self.identity_providers_mock.create.assert_called_with(
            id=identity_fakes.idp_id,
            **kwargs
        )

        collist = ('description', 'enabled', 'id')
        self.assertEqual(columns, collist)
        datalist = (
            None,
            False,
            identity_fakes.idp_id,
        )
        self.assertEqual(data, datalist)


class TestIdentityProviderDelete(TestIdentityProvider):

    def setUp(self):
        super(TestIdentityProviderDelete, self).setUp()

        # This is the return value for utils.find_resource()
        self.identity_providers_mock.get.return_value = fakes.FakeResource(
            None,
            copy.deepcopy(identity_fakes.IDENTITY_PROVIDER),
            loaded=True,
        )

        self.identity_providers_mock.delete.return_value = None
        self.cmd = identity_provider.DeleteIdentityProvider(self.app, None)

    def test_delete_identity_provider(self):
        arglist = [
            identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider', identity_fakes.idp_id),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)
        self.cmd.take_action(parsed_args)
        self.identity_providers_mock.delete.assert_called_with(
            identity_fakes.idp_id,
        )


class TestIdentityProviderList(TestIdentityProvider):

    def setUp(self):
        super(TestIdentityProviderList, self).setUp()

        self.identity_providers_mock.get.return_value = fakes.FakeResource(
            None,
            copy.deepcopy(identity_fakes.IDENTITY_PROVIDER),
            loaded=True,
        )
        self.identity_providers_mock.list.return_value = [
            fakes.FakeResource(
                None,
                copy.deepcopy(identity_fakes.IDENTITY_PROVIDER),
                loaded=True,
            ),
        ]

        # Get the command object to test
        self.cmd = identity_provider.ListIdentityProvider(self.app, None)

    def test_identity_provider_list_no_options(self):
        arglist = []
        verifylist = []
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)

        # DisplayCommandBase.take_action() returns two tuples
        columns, data = self.cmd.take_action(parsed_args)

        self.identity_providers_mock.list.assert_called_with()

        collist = ('ID', 'Enabled', 'Description')
        self.assertEqual(columns, collist)
        datalist = ((
            identity_fakes.idp_id,
            True,
            identity_fakes.idp_description,
        ), )
        self.assertEqual(tuple(data), datalist)


class TestIdentityProviderShow(TestIdentityProvider):

    def setUp(self):
        super(TestIdentityProviderShow, self).setUp()

        ret = fakes.FakeResource(
            None,
            copy.deepcopy(identity_fakes.IDENTITY_PROVIDER),
            loaded=True,
        )
        self.identity_providers_mock.get.return_value = ret
        # Get the command object to test
        self.cmd = identity_provider.ShowIdentityProvider(self.app, None)

    def test_identity_provider_show(self):
        arglist = [
            identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider', identity_fakes.idp_id),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)

        columns, data = self.cmd.take_action(parsed_args)

        self.identity_providers_mock.get.assert_called_with(
            identity_fakes.idp_id,
        )

        collist = ('description', 'enabled', 'id')
        self.assertEqual(columns, collist)
        datalist = (
            identity_fakes.idp_description,
            True,
            identity_fakes.idp_id,
        )
        self.assertEqual(data, datalist)


class TestIdentityProviderSet(TestIdentityProvider):

    def setUp(self):
        super(TestIdentityProviderSet, self).setUp()
        self.cmd = identity_provider.SetIdentityProvider(self.app, None)

    def test_identity_provider_disable(self):
        """Disable Identity Provider

        Set Identity Provider's ``enabled`` attribute to False.
        """
        def prepare(self):
            """Prepare fake return objects before the test is executed"""
            updated_idp = copy.deepcopy(identity_fakes.IDENTITY_PROVIDER)
            updated_idp['enabled'] = False
            resources = fakes.FakeResource(
                None,
                updated_idp,
                loaded=True
            )
            self.identity_providers_mock.update.return_value = resources

        prepare(self)
        arglist = [
            '--disable', identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider', identity_fakes.idp_id),
            ('enable', False),
            ('disable', True),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)

        columns, data = self.cmd.take_action(parsed_args)
        self.identity_providers_mock.update.assert_called_with(
            identity_fakes.idp_id,
            enabled=False,
        )

        collist = ('description', 'enabled', 'id')
        self.assertEqual(columns, collist)
        datalist = (
            identity_fakes.idp_description,
            False,
            identity_fakes.idp_id,
        )
        self.assertEqual(datalist, data)

    def test_identity_provider_enable(self):
        """Enable Identity Provider.

        Set Identity Provider's ``enabled`` attribute to True.
        """
        def prepare(self):
            """Prepare fake return objects before the test is executed"""
            resources = fakes.FakeResource(
                None,
                copy.deepcopy(identity_fakes.IDENTITY_PROVIDER),
                loaded=True
            )
            self.identity_providers_mock.update.return_value = resources

        prepare(self)
        arglist = [
            '--enable', identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider', identity_fakes.idp_id),
            ('enable', True),
            ('disable', False),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)

        columns, data = self.cmd.take_action(parsed_args)
        self.identity_providers_mock.update.assert_called_with(
            identity_fakes.idp_id, enabled=True)
        collist = ('description', 'enabled', 'id')
        self.assertEqual(columns, collist)
        datalist = (
            identity_fakes.idp_description,
            True,
            identity_fakes.idp_id,
        )
        self.assertEqual(data, datalist)

    def test_identity_provider_no_options(self):
        def prepare(self):
            """Prepare fake return objects before the test is executed"""
            resources = fakes.FakeResource(
                None,
                copy.deepcopy(identity_fakes.IDENTITY_PROVIDER),
                loaded=True
            )
            self.identity_providers_mock.get.return_value = resources

            resources = fakes.FakeResource(
                None,
                copy.deepcopy(identity_fakes.IDENTITY_PROVIDER),
                loaded=True,
            )
            self.identity_providers_mock.update.return_value = resources

        prepare(self)
        arglist = [
            identity_fakes.idp_id,
        ]
        verifylist = [
            ('identity_provider', identity_fakes.idp_id),
            ('enable', False),
            ('disable', False),
        ]
        parsed_args = self.check_parser(self.cmd, arglist, verifylist)

        columns, data = self.cmd.take_action(parsed_args)

        # expect take_action() to return (None, None) as
        # neither --enable nor --disable was specified
        self.assertEqual(columns, None)
        self.assertEqual(data, None)
