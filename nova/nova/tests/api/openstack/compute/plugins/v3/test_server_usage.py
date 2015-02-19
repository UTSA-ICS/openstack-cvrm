# Copyright 2013 OpenStack Foundation
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

import datetime

from nova import compute
from nova import db
from nova import exception
from nova.objects import instance as instance_obj
from nova.openstack.common import jsonutils
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance

UUID1 = '00000000-0000-0000-0000-000000000001'
UUID2 = '00000000-0000-0000-0000-000000000002'
UUID3 = '00000000-0000-0000-0000-000000000003'

DATE1 = datetime.datetime(year=2013, month=4, day=5, hour=12)
DATE2 = datetime.datetime(year=2013, month=4, day=5, hour=13)
DATE3 = datetime.datetime(year=2013, month=4, day=5, hour=14)


def fake_compute_get(*args, **kwargs):
    inst = fakes.stub_instance(1, uuid=UUID3, launched_at=DATE1,
                               terminated_at=DATE2)
    return fake_instance.fake_instance_obj(args[1], **inst)


def fake_compute_get_all(*args, **kwargs):
    db_list = [
        fakes.stub_instance(2, uuid=UUID1, launched_at=DATE2,
                            terminated_at=DATE3),
        fakes.stub_instance(3, uuid=UUID2, launched_at=DATE1,
                            terminated_at=DATE3),
    ]
    fields = instance_obj.INSTANCE_DEFAULT_FIELDS
    return instance_obj._make_instance_list(args[1],
                                            instance_obj.InstanceList(),
                                            db_list, fields)


class ServerUsageTest(test.TestCase):
    content_type = 'application/json'
    prefix = 'os-server-usage:'

    def setUp(self):
        super(ServerUsageTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)
        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        self.stubs.Set(compute.api.API, 'get_all', fake_compute_get_all)
        return_server = fakes.fake_instance_get()
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

    def _make_request(self, url):
        req = fakes.HTTPRequestV3.blank(url)
        req.accept = self.content_type
        res = req.get_response(fakes.wsgi_app_v3(init_only=(
            'servers', 'os-server-usage')))
        return res

    def _get_server(self, body):
        return jsonutils.loads(body).get('server')

    def _get_servers(self, body):
        return jsonutils.loads(body).get('servers')

    def assertServerUsage(self, server, launched_at, terminated_at):
        resp_launched_at = timeutils.parse_isotime(
            server.get('%slaunched_at' % self.prefix))
        self.assertEqual(timeutils.normalize_time(resp_launched_at),
                         launched_at)
        resp_terminated_at = timeutils.parse_isotime(
            server.get('%sterminated_at' % self.prefix))
        self.assertEqual(timeutils.normalize_time(resp_terminated_at),
                         terminated_at)

    def test_show(self):
        url = '/v3/servers/%s' % UUID3
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        now = timeutils.utcnow()
        timeutils.set_time_override(now)
        self.assertServerUsage(self._get_server(res.body),
                               launched_at=DATE1,
                               terminated_at=DATE2)

    def test_detail(self):
        url = '/v3/servers/detail'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 200)
        servers = self._get_servers(res.body)
        self.assertServerUsage(servers[0],
                               launched_at=DATE2,
                               terminated_at=DATE3)
        self.assertServerUsage(servers[1],
                               launched_at=DATE1,
                               terminated_at=DATE3)

    def test_no_instance_passthrough_404(self):

        def fake_compute_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(compute.api.API, 'get', fake_compute_get)
        url = '/v3/servers/70f6db34-de8d-4fbd-aafb-4065bdfa6115'
        res = self._make_request(url)

        self.assertEqual(res.status_int, 404)
