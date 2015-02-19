# Copyright 2010-2011 OpenStack Foundation
# Copyright 2011 Piston Cloud Computing, Inc.
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
import uuid as stdlib_uuid

import webob

from nova.api.openstack.compute.plugins.v3 import consoles
from nova.compute import vm_states
from nova import console
from nova import db
from nova import exception
from nova.openstack.common import timeutils
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import matchers


FAKE_UUID = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'


class FakeInstanceDB(object):

    def __init__(self):
        self.instances_by_id = {}
        self.ids_by_uuid = {}
        self.max_id = 0

    def return_server_by_id(self, context, id):
        if id not in self.instances_by_id:
            self._add_server(id=id)
        return dict(self.instances_by_id[id])

    def return_server_by_uuid(self, context, uuid):
        if uuid not in self.ids_by_uuid:
            self._add_server(uuid=uuid)
        return dict(self.instances_by_id[self.ids_by_uuid[uuid]])

    def _add_server(self, id=None, uuid=None):
        if id is None:
            id = self.max_id + 1
        if uuid is None:
            uuid = str(stdlib_uuid.uuid4())
        instance = stub_instance(id, uuid=uuid)
        self.instances_by_id[id] = instance
        self.ids_by_uuid[uuid] = id
        if id > self.max_id:
            self.max_id = id


def stub_instance(id, user_id='fake', project_id='fake', host=None,
                  vm_state=None, task_state=None,
                  reservation_id="", uuid=FAKE_UUID, image_ref="10",
                  flavor_id="1", name=None, key_name='',
                  access_ipv4=None, access_ipv6=None, progress=0):

    if host is not None:
        host = str(host)

    if key_name:
        key_data = 'FAKE'
    else:
        key_data = ''

    # ReservationID isn't sent back, hack it in there.
    server_name = name or "server%s" % id
    if reservation_id != "":
        server_name = "reservation_%s" % (reservation_id, )

    instance = {
        "id": int(id),
        "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
        "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
        "admin_password": "",
        "user_id": user_id,
        "project_id": project_id,
        "image_ref": image_ref,
        "kernel_id": "",
        "ramdisk_id": "",
        "launch_index": 0,
        "key_name": key_name,
        "key_data": key_data,
        "vm_state": vm_state or vm_states.BUILDING,
        "task_state": task_state,
        "memory_mb": 0,
        "vcpus": 0,
        "root_gb": 0,
        "hostname": "",
        "host": host,
        "instance_type": {},
        "user_data": "",
        "reservation_id": reservation_id,
        "mac_address": "",
        "scheduled_at": timeutils.utcnow(),
        "launched_at": timeutils.utcnow(),
        "terminated_at": timeutils.utcnow(),
        "availability_zone": "",
        "display_name": server_name,
        "display_description": "",
        "locked": False,
        "metadata": [],
        "access_ip_v4": access_ipv4,
        "access_ip_v6": access_ipv6,
        "uuid": uuid,
        "progress": progress}

    return instance


class ConsolesControllerTest(test.NoDBTestCase):
    def setUp(self):
        super(ConsolesControllerTest, self).setUp()
        self.flags(verbose=True)
        self.instance_db = FakeInstanceDB()
        self.stubs.Set(db, 'instance_get',
                       self.instance_db.return_server_by_id)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       self.instance_db.return_server_by_uuid)
        self.uuid = str(stdlib_uuid.uuid4())
        self.url = '/v3/fake/servers/%s/consoles' % self.uuid
        self.controller = consoles.ConsolesController()

    def test_create_console(self):
        def fake_create_console(cons_self, context, instance_id):
            self.assertEqual(instance_id, self.uuid)
            return {}
        self.stubs.Set(console.api.API, 'create_console', fake_create_console)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.controller.create(req, self.uuid, None)
        self.assertEqual(self.controller.create.wsgi_code, 201)

    def test_create_console_unknown_instance(self):
        def fake_create_console(cons_self, context, instance_id):
            raise exception.InstanceNotFound(instance_id=instance_id)
        self.stubs.Set(console.api.API, 'create_console', fake_create_console)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.create,
                          req, self.uuid, None)

    def test_show_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, self.uuid)
            self.assertEqual(console_id, 20)
            pool = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            return dict(id=console_id, password='fake_password',
                    port='fake_port', pool=pool, instance_name='inst-0001')

        expected = {'console': {'id': 20,
                                'port': 'fake_port',
                                'host': 'fake_hostname',
                                'password': 'fake_password',
                                'instance_name': 'inst-0001',
                                'console_type': 'fake_type'}}

        self.stubs.Set(console.api.API, 'get_console', fake_get_console)

        req = fakes.HTTPRequestV3.blank(self.url + '/20')
        res_dict = self.controller.show(req, self.uuid, '20')
        self.assertThat(res_dict, matchers.DictMatches(expected))

    def test_show_console_unknown_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFound(console_id=console_id)

        self.stubs.Set(console.api.API, 'get_console', fake_get_console)

        req = fakes.HTTPRequestV3.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, self.uuid, '20')

    def test_show_console_unknown_instance(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFoundForInstance(
                instance_uuid=instance_id)

        self.stubs.Set(console.api.API, 'get_console', fake_get_console)

        req = fakes.HTTPRequestV3.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.show,
                          req, self.uuid, '20')

    def test_list_consoles(self):
        def fake_get_consoles(cons_self, context, instance_id):
            self.assertEqual(instance_id, self.uuid)

            pool1 = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            cons1 = dict(id=10, password='fake_password',
                    port='fake_port', pool=pool1)
            pool2 = dict(console_type='fake_type2',
                    public_hostname='fake_hostname2')
            cons2 = dict(id=11, password='fake_password2',
                    port='fake_port2', pool=pool2)
            return [cons1, cons2]

        expected = {'consoles':
                [{'id': 10, 'console_type': 'fake_type'},
                 {'id': 11, 'console_type': 'fake_type2'}]}

        self.stubs.Set(console.api.API, 'get_consoles', fake_get_consoles)

        req = fakes.HTTPRequestV3.blank(self.url)
        res_dict = self.controller.index(req, self.uuid)
        self.assertThat(res_dict, matchers.DictMatches(expected))

    def test_list_consoles_unknown_instance(self):
        def fake_get_consoles(cons_self, context, instance_id):
            raise exception.InstanceNotFound(instance_id=instance_id)
        self.stubs.Set(console.api.API, 'get_consoles', fake_get_consoles)

        req = fakes.HTTPRequestV3.blank(self.url)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.index,
                          req, self.uuid)

    def test_delete_console(self):
        def fake_get_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, self.uuid)
            self.assertEqual(console_id, 20)
            pool = dict(console_type='fake_type',
                    public_hostname='fake_hostname')
            return dict(id=console_id, password='fake_password',
                    port='fake_port', pool=pool)

        def fake_delete_console(cons_self, context, instance_id, console_id):
            self.assertEqual(instance_id, self.uuid)
            self.assertEqual(console_id, 20)

        self.stubs.Set(console.api.API, 'get_console', fake_get_console)
        self.stubs.Set(console.api.API, 'delete_console', fake_delete_console)

        req = fakes.HTTPRequestV3.blank(self.url + '/20')
        self.controller.delete(req, self.uuid, '20')

    def test_delete_console_unknown_console(self):
        def fake_delete_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFound(console_id=console_id)

        self.stubs.Set(console.api.API, 'delete_console', fake_delete_console)

        req = fakes.HTTPRequestV3.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, self.uuid, '20')

    def test_delete_console_unknown_instance(self):
        def fake_delete_console(cons_self, context, instance_id, console_id):
            raise exception.ConsoleNotFoundForInstance(
                instance_uuid=instance_id)

        self.stubs.Set(console.api.API, 'delete_console', fake_delete_console)

        req = fakes.HTTPRequestV3.blank(self.url + '/20')
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.delete,
                          req, self.uuid, '20')
