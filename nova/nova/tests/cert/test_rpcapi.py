# Copyright 2012, Red Hat, Inc.
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

"""
Unit Tests for nova.cert.rpcapi
"""

import contextlib

import mock
from oslo.config import cfg

from nova.cert import rpcapi as cert_rpcapi
from nova import context
from nova import test

CONF = cfg.CONF


class CertRpcAPITestCase(test.NoDBTestCase):
    def _test_cert_api(self, method, **kwargs):
        ctxt = context.RequestContext('fake_user', 'fake_project')

        rpcapi = cert_rpcapi.CertAPI()
        self.assertIsNotNone(rpcapi.client)
        self.assertEqual(rpcapi.client.target.topic, CONF.cert_topic)

        orig_prepare = rpcapi.client.prepare
        expected_version = kwargs.pop('version', rpcapi.client.target.version)

        with contextlib.nested(
            mock.patch.object(rpcapi.client, 'call'),
            mock.patch.object(rpcapi.client, 'prepare'),
            mock.patch.object(rpcapi.client, 'can_send_version'),
        ) as (
            rpc_mock, prepare_mock, csv_mock
        ):
            prepare_mock.return_value = rpcapi.client
            rpc_mock.return_value = 'foo'
            csv_mock.side_effect = (
                lambda v: orig_prepare(version=v).can_send_version())

            retval = getattr(rpcapi, method)(ctxt, **kwargs)
            self.assertEqual(retval, rpc_mock.return_value)

            prepare_mock.assert_called_once_with(version=expected_version)
            rpc_mock.assert_called_once_with(ctxt, method, **kwargs)

    def test_revoke_certs_by_user(self):
        self._test_cert_api('revoke_certs_by_user', user_id='fake_user_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('revoke_certs_by_user', user_id='fake_user_id',
                version='1.0')

    def test_revoke_certs_by_project(self):
        self._test_cert_api('revoke_certs_by_project',
                            project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('revoke_certs_by_project',
                            project_id='fake_project_id', version='1.0')

    def test_revoke_certs_by_user_and_project(self):
        self._test_cert_api('revoke_certs_by_user_and_project',
                            user_id='fake_user_id',
                            project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('revoke_certs_by_user_and_project',
                            user_id='fake_user_id',
                            project_id='fake_project_id', version='1.0')

    def test_generate_x509_cert(self):
        self._test_cert_api('generate_x509_cert',
                            user_id='fake_user_id',
                            project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('generate_x509_cert',
                            user_id='fake_user_id',
                            project_id='fake_project_id', version='1.0')

    def test_fetch_ca(self):
        self._test_cert_api('fetch_ca', project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('fetch_ca', project_id='fake_project_id',
                version='1.0')

    def test_fetch_crl(self):
        self._test_cert_api('fetch_crl', project_id='fake_project_id')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('fetch_crl', project_id='fake_project_id',
                version='1.0')

    def test_decrypt_text(self):
        self._test_cert_api('decrypt_text',
                            project_id='fake_project_id', text='blah')

        # NOTE(russellb) Havana compat
        self.flags(cert='havana', group='upgrade_levels')
        self._test_cert_api('decrypt_text',
                            project_id='fake_project_id', text='blah',
                            version='1.0')
