# Copyright 2012 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import os
import uuid

from keystoneclient.contrib.ec2 import utils as ec2_utils

from keystone import config
from keystone import tests
from keystone.tests import test_keystoneclient


CONF = config.CONF


class KcMasterSqlTestCase(test_keystoneclient.KcMasterTestCase):
    def config_files(self):
        config_files = super(KcMasterSqlTestCase, self).config_files()
        config_files.append(tests.dirs.tests_conf('backend_sql.conf'))
        return config_files

    def setUp(self):
        super(KcMasterSqlTestCase, self).setUp()
        self.default_client = self.get_client()
        self.addCleanup(self.cleanup_instance('default_client'))

    def test_endpoint_crud(self):
        from keystoneclient import exceptions as client_exceptions

        client = self.get_client(admin=True)

        service = client.services.create(name=uuid.uuid4().hex,
                                         service_type=uuid.uuid4().hex,
                                         description=uuid.uuid4().hex)

        endpoint_region = uuid.uuid4().hex
        invalid_service_id = uuid.uuid4().hex
        endpoint_publicurl = uuid.uuid4().hex
        endpoint_internalurl = uuid.uuid4().hex
        endpoint_adminurl = uuid.uuid4().hex

        # a non-existent service ID should trigger a 404
        self.assertRaises(client_exceptions.NotFound,
                          client.endpoints.create,
                          region=endpoint_region,
                          service_id=invalid_service_id,
                          publicurl=endpoint_publicurl,
                          adminurl=endpoint_adminurl,
                          internalurl=endpoint_internalurl)

        endpoint = client.endpoints.create(region=endpoint_region,
                                           service_id=service.id,
                                           publicurl=endpoint_publicurl,
                                           adminurl=endpoint_adminurl,
                                           internalurl=endpoint_internalurl)

        self.assertEqual(endpoint.region, endpoint_region)
        self.assertEqual(endpoint.service_id, service.id)
        self.assertEqual(endpoint.publicurl, endpoint_publicurl)
        self.assertEqual(endpoint.internalurl, endpoint_internalurl)
        self.assertEqual(endpoint.adminurl, endpoint_adminurl)

        client.endpoints.delete(id=endpoint.id)
        self.assertRaises(client_exceptions.NotFound, client.endpoints.delete,
                          id=endpoint.id)

    def _send_ec2_auth_request(self, credentials, client=None):
        if not client:
            client = self.default_client
        url = '%s/ec2tokens' % self.default_client.auth_url
        (resp, token) = client.request(
            url=url, method='POST',
            body={'credentials': credentials})
        return resp, token

    def _generate_default_user_ec2_credentials(self):
        cred = self. default_client.ec2.create(
            user_id=self.user_foo['id'],
            tenant_id=self.tenant_bar['id'])
        return self._generate_user_ec2_credentials(cred.access, cred.secret)

    def _generate_user_ec2_credentials(self, access, secret):
        signer = ec2_utils.Ec2Signer(secret)
        credentials = {'params': {'SignatureVersion': '2'},
                       'access': access,
                       'verb': 'GET',
                       'host': 'localhost',
                       'path': '/service/cloud'}
        signature = signer.generate(credentials)
        return credentials, signature

    def test_ec2_auth_success(self):
        credentials, signature = self._generate_default_user_ec2_credentials()
        credentials['signature'] = signature
        resp, token = self._send_ec2_auth_request(credentials)
        self.assertEqual(resp.status_code, 200)
        self.assertIn('access', token)

    def test_ec2_auth_success_trust(self):
        # Add "other" role user_foo and create trust delegating it to user_two
        self.assignment_api.add_role_to_user_and_project(
            self.user_foo['id'],
            self.tenant_bar['id'],
            self.role_other['id'])
        trust_id = 'atrust123'
        trust = {'trustor_user_id': self.user_foo['id'],
                 'trustee_user_id': self.user_two['id'],
                 'project_id': self.tenant_bar['id'],
                 'impersonation': True}
        roles = [self.role_other]
        self.trust_api.create_trust(trust_id, trust, roles)

        # Create a client for user_two, scoped to the trust
        client = self.get_client(self.user_two)
        ret = client.authenticate(trust_id=trust_id,
                                  tenant_id=self.tenant_bar['id'])
        self.assertTrue(ret)
        self.assertTrue(client.auth_ref.trust_scoped)
        self.assertEqual(trust_id, client.auth_ref.trust_id)

        # Create an ec2 keypair using the trust client impersonating user_foo
        cred = client.ec2.create(user_id=self.user_foo['id'],
                                 tenant_id=self.tenant_bar['id'])
        credentials, signature = self._generate_user_ec2_credentials(
            cred.access, cred.secret)
        credentials['signature'] = signature
        resp, token = self._send_ec2_auth_request(credentials)
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(trust_id, token['access']['trust']['id'])
        #TODO(shardy) we really want to check the roles and trustee
        # but because of where the stubbing happens we don't seem to
        # hit the necessary code in controllers.py _authenticate_token
        # so although all is OK via a real request, it incorrect in
        # this test..

    def test_ec2_auth_failure(self):
        from keystoneclient import exceptions as client_exceptions

        credentials, signature = self._generate_default_user_ec2_credentials()
        credentials['signature'] = uuid.uuid4().hex
        self.assertRaises(client_exceptions.Unauthorized,
                          self._send_ec2_auth_request,
                          credentials)

    def test_ec2_credential_crud(self):
        creds = self.default_client.ec2.list(user_id=self.user_foo['id'])
        self.assertEqual(creds, [])

        cred = self.default_client.ec2.create(user_id=self.user_foo['id'],
                                              tenant_id=self.tenant_bar['id'])
        creds = self.default_client.ec2.list(user_id=self.user_foo['id'])
        self.assertEqual(creds, [cred])
        got = self.default_client.ec2.get(user_id=self.user_foo['id'],
                                          access=cred.access)
        self.assertEqual(cred, got)

        self.default_client.ec2.delete(user_id=self.user_foo['id'],
                                       access=cred.access)
        creds = self.default_client.ec2.list(user_id=self.user_foo['id'])
        self.assertEqual(creds, [])

    def test_ec2_credential_crud_non_admin(self):
        na_client = self.get_client(self.user_two)
        creds = na_client.ec2.list(user_id=self.user_two['id'])
        self.assertEqual(creds, [])

        cred = na_client.ec2.create(user_id=self.user_two['id'],
                                    tenant_id=self.tenant_baz['id'])
        creds = na_client.ec2.list(user_id=self.user_two['id'])
        self.assertEqual(creds, [cred])
        got = na_client.ec2.get(user_id=self.user_two['id'],
                                access=cred.access)
        self.assertEqual(cred, got)

        na_client.ec2.delete(user_id=self.user_two['id'],
                             access=cred.access)
        creds = na_client.ec2.list(user_id=self.user_two['id'])
        self.assertEqual(creds, [])

    def test_ec2_list_credentials(self):
        cred_1 = self.default_client.ec2.create(
            user_id=self.user_foo['id'],
            tenant_id=self.tenant_bar['id'])
        cred_2 = self.default_client.ec2.create(
            user_id=self.user_foo['id'],
            tenant_id=self.tenant_service['id'])
        cred_3 = self.default_client.ec2.create(
            user_id=self.user_foo['id'],
            tenant_id=self.tenant_mtu['id'])
        two = self.get_client(self.user_two)
        cred_4 = two.ec2.create(user_id=self.user_two['id'],
                                tenant_id=self.tenant_bar['id'])
        creds = self.default_client.ec2.list(user_id=self.user_foo['id'])
        self.assertEqual(len(creds), 3)
        self.assertEqual(sorted([cred_1, cred_2, cred_3],
                                key=lambda x: x.access),
                         sorted(creds, key=lambda x: x.access))
        self.assertNotIn(cred_4, creds)

    def test_ec2_credentials_create_404(self):
        from keystoneclient import exceptions as client_exceptions
        self.assertRaises(client_exceptions.NotFound,
                          self.default_client.ec2.create,
                          user_id=uuid.uuid4().hex,
                          tenant_id=self.tenant_bar['id'])
        self.assertRaises(client_exceptions.NotFound,
                          self.default_client.ec2.create,
                          user_id=self.user_foo['id'],
                          tenant_id=uuid.uuid4().hex)

    def test_ec2_credentials_delete_404(self):
        from keystoneclient import exceptions as client_exceptions

        self.assertRaises(client_exceptions.NotFound,
                          self.default_client.ec2.delete,
                          user_id=uuid.uuid4().hex,
                          access=uuid.uuid4().hex)

    def test_ec2_credentials_get_404(self):
        from keystoneclient import exceptions as client_exceptions

        self.assertRaises(client_exceptions.NotFound,
                          self.default_client.ec2.get,
                          user_id=uuid.uuid4().hex,
                          access=uuid.uuid4().hex)

    def test_ec2_credentials_list_404(self):
        from keystoneclient import exceptions as client_exceptions

        self.assertRaises(client_exceptions.NotFound,
                          self.default_client.ec2.list,
                          user_id=uuid.uuid4().hex)

    def test_ec2_credentials_list_user_forbidden(self):
        from keystoneclient import exceptions as client_exceptions

        two = self.get_client(self.user_two)
        self.assertRaises(client_exceptions.Forbidden, two.ec2.list,
                          user_id=self.user_foo['id'])

    def test_ec2_credentials_get_user_forbidden(self):
        from keystoneclient import exceptions as client_exceptions

        cred = self.default_client.ec2.create(user_id=self.user_foo['id'],
                                              tenant_id=self.tenant_bar['id'])

        two = self.get_client(self.user_two)
        self.assertRaises(client_exceptions.Forbidden, two.ec2.get,
                          user_id=self.user_foo['id'], access=cred.access)

        self.default_client.ec2.delete(user_id=self.user_foo['id'],
                                       access=cred.access)

    def test_ec2_credentials_delete_user_forbidden(self):
        from keystoneclient import exceptions as client_exceptions

        cred = self.default_client.ec2.create(user_id=self.user_foo['id'],
                                              tenant_id=self.tenant_bar['id'])

        two = self.get_client(self.user_two)
        self.assertRaises(client_exceptions.Forbidden, two.ec2.delete,
                          user_id=self.user_foo['id'], access=cred.access)

        self.default_client.ec2.delete(user_id=self.user_foo['id'],
                                       access=cred.access)

    def test_endpoint_create_404(self):
        from keystoneclient import exceptions as client_exceptions
        client = self.get_client(admin=True)
        self.assertRaises(client_exceptions.NotFound,
                          client.endpoints.create,
                          region=uuid.uuid4().hex,
                          service_id=uuid.uuid4().hex,
                          publicurl=uuid.uuid4().hex,
                          adminurl=uuid.uuid4().hex,
                          internalurl=uuid.uuid4().hex)

    def test_endpoint_delete_404(self):
        from keystoneclient import exceptions as client_exceptions
        client = self.get_client(admin=True)
        self.assertRaises(client_exceptions.NotFound,
                          client.endpoints.delete,
                          id=uuid.uuid4().hex)

    def test_policy_crud(self):
        # FIXME(dolph): this test was written prior to the v3 implementation of
        #               the client and essentially refers to a non-existent
        #               policy manager in the v2 client. this test needs to be
        #               moved to a test suite running against the v3 api
        self.skipTest('Written prior to v3 client; needs refactor')

        from keystoneclient import exceptions as client_exceptions
        client = self.get_client(admin=True)

        policy_blob = uuid.uuid4().hex
        policy_type = uuid.uuid4().hex
        service = client.services.create(
            name=uuid.uuid4().hex,
            service_type=uuid.uuid4().hex,
            description=uuid.uuid4().hex)
        endpoint = client.endpoints.create(
            service_id=service.id,
            region=uuid.uuid4().hex,
            adminurl=uuid.uuid4().hex,
            internalurl=uuid.uuid4().hex,
            publicurl=uuid.uuid4().hex)

        # create
        policy = client.policies.create(
            blob=policy_blob,
            type=policy_type,
            endpoint=endpoint.id)
        self.assertEqual(policy_blob, policy.policy)
        self.assertEqual(policy_type, policy.type)
        self.assertEqual(endpoint.id, policy.endpoint_id)

        policy = client.policies.get(policy=policy.id)
        self.assertEqual(policy_blob, policy.policy)
        self.assertEqual(policy_type, policy.type)
        self.assertEqual(endpoint.id, policy.endpoint_id)

        endpoints = [x for x in client.endpoints.list() if x.id == endpoint.id]
        endpoint = endpoints[0]
        self.assertEqual(policy_blob, policy.policy)
        self.assertEqual(policy_type, policy.type)
        self.assertEqual(endpoint.id, policy.endpoint_id)

        # update
        policy_blob = uuid.uuid4().hex
        policy_type = uuid.uuid4().hex
        endpoint = client.endpoints.create(
            service_id=service.id,
            region=uuid.uuid4().hex,
            adminurl=uuid.uuid4().hex,
            internalurl=uuid.uuid4().hex,
            publicurl=uuid.uuid4().hex)

        policy = client.policies.update(
            policy=policy.id,
            blob=policy_blob,
            type=policy_type,
            endpoint=endpoint.id)

        policy = client.policies.get(policy=policy.id)
        self.assertEqual(policy_blob, policy.policy)
        self.assertEqual(policy_type, policy.type)
        self.assertEqual(endpoint.id, policy.endpoint_id)

        # delete
        client.policies.delete(policy=policy.id)
        self.assertRaises(
            client_exceptions.NotFound,
            client.policies.get,
            policy=policy.id)
        policies = [x for x in client.policies.list() if x.id == policy.id]
        self.assertEqual(len(policies), 0)


class KcOptTestCase(KcMasterSqlTestCase):
    # Set KSCTEST_PATH to the keystoneclient directory, then run this test.
    #
    # For example, to test your local keystoneclient,
    #
    # KSCTEST_PATH=/opt/stack/python-keystoneclient \
    #  tox -e py27 test_keystoneclient_sql.KcOptTestCase

    def setUp(self):
        self.checkout_info = os.environ.get('KSCTEST_PATH')
        if not self.checkout_info:
            self.skip('Set KSCTEST_PATH env to test with local client')
        super(KcOptTestCase, self).setUp()
