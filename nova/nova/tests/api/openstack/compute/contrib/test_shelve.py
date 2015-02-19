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

import uuid
import webob

from nova.api.openstack.compute.contrib import shelve
from nova.compute import api as compute_api
from nova import db
from nova import exception
from nova.openstack.common import policy
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance


def fake_instance_get_by_uuid(context, instance_id,
                              columns_to_join=None, use_slave=False):
    return fake_instance.fake_db_instance(
        **{'name': 'fake', 'project_id': '%s_unequal' % context.project_id})


def fake_auth_context(context):
    return True


class ShelvePolicyTest(test.NoDBTestCase):
    def setUp(self):
        super(ShelvePolicyTest, self).setUp()
        self.controller = shelve.ShelveController()

    def test_shelve_restricted_by_role(self):
        rules = policy.Rules({'compute_extension:shelve':
                              policy.parse_rule('role:admin')})
        policy.set_rules(rules)

        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._shelve,
                req, str(uuid.uuid4()), {})

    def test_shelve_allowed(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:shelve':
                              policy.parse_rule('')})
        policy.set_rules(rules)

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._shelve,
                req, str(uuid.uuid4()), {})

    def test_shelve_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(shelve, 'auth_shelve', fake_auth_context)
        self.stubs.Set(compute_api.API, 'shelve',
                       fakes.fake_actions_to_locked_server)
        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(webob.exc.HTTPConflict, self.controller._shelve,
                          req, str(uuid.uuid4()), {})

    def test_unshelve_restricted_by_role(self):
        rules = policy.Rules({'compute_extension:unshelve':
                              policy.parse_rule('role:admin')})
        policy.set_rules(rules)

        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._unshelve,
                req, str(uuid.uuid4()), {})

    def test_unshelve_allowed(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:unshelve':
                              policy.parse_rule('')})
        policy.set_rules(rules)

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized, self.controller._unshelve,
                req, str(uuid.uuid4()), {})

    def test_unshelve_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(shelve, 'auth_unshelve', fake_auth_context)
        self.stubs.Set(compute_api.API, 'unshelve',
                       fakes.fake_actions_to_locked_server)
        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(webob.exc.HTTPConflict, self.controller._unshelve,
                          req, str(uuid.uuid4()), {})

    def test_shelve_offload_restricted_by_role(self):
        rules = policy.Rules({'compute_extension:shelveOffload':
                              policy.parse_rule('role:admin')})
        policy.set_rules(rules)

        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized,
                self.controller._shelve_offload, req, str(uuid.uuid4()), {})

    def test_shelve_offload_allowed(self):
        rules = policy.Rules({'compute:get': policy.parse_rule(''),
                              'compute_extension:shelveOffload':
                              policy.parse_rule('')})
        policy.set_rules(rules)

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(exception.NotAuthorized,
                self.controller._shelve_offload, req, str(uuid.uuid4()), {})

    def test_shelve_offload_locked_server(self):
        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get_by_uuid)
        self.stubs.Set(shelve, 'auth_shelve_offload', fake_auth_context)
        self.stubs.Set(compute_api.API, 'shelve_offload',
                       fakes.fake_actions_to_locked_server)
        req = fakes.HTTPRequest.blank('/v2/123/servers/12/os-shelve')
        self.assertRaises(webob.exc.HTTPConflict,
                          self.controller._shelve_offload,
                          req, str(uuid.uuid4()), {})
