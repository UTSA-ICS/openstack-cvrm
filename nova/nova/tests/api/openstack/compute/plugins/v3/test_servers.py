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

import base64
import datetime
import uuid

import iso8601
import mox
from oslo.config import cfg
import six.moves.urllib.parse as urlparse
import testtools
import webob

from nova.api.openstack import compute
from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import access_ips
from nova.api.openstack.compute.plugins.v3 import ips
from nova.api.openstack.compute.plugins.v3 import keypairs
from nova.api.openstack.compute.plugins.v3 import servers
from nova.api.openstack.compute import views
from nova.api.openstack import extensions
from nova.compute import api as compute_api
from nova.compute import flavors
from nova.compute import task_states
from nova.compute import vm_states
from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova.image import glance
from nova.network import manager
from nova.network.neutronv2 import api as neutron_api
from nova.objects import instance as instance_obj
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import policy as common_policy
from nova.openstack.common import timeutils
from nova import policy
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import fake_instance
from nova.tests import fake_network
from nova.tests.image import fake
from nova.tests import matchers
from nova import utils as nova_utils

CONF = cfg.CONF
CONF.import_opt('password_length', 'nova.utils')

FAKE_UUID = fakes.FAKE_UUID

INSTANCE_IDS = {FAKE_UUID: 1}
FIELDS = instance_obj.INSTANCE_DEFAULT_FIELDS


def fake_gen_uuid():
    return FAKE_UUID


def return_servers_empty(context, *args, **kwargs):
    return []


def instance_update_and_get_original(context, instance_uuid, values,
                                     update_cells=True,
                                     columns_to_join=None,
                                     ):
    inst = fakes.stub_instance(INSTANCE_IDS.get(instance_uuid),
                               name=values.get('display_name'))
    inst = dict(inst, **values)
    return (inst, inst)


def instance_update(context, instance_uuid, values, update_cells=True):
    inst = fakes.stub_instance(INSTANCE_IDS.get(instance_uuid),
                               name=values.get('display_name'))
    inst = dict(inst, **values)
    return inst


def fake_compute_api(cls, req, id):
    return True


def fake_start_stop_not_ready(self, context, instance):
    raise exception.InstanceNotReady(instance_id=instance["uuid"])


def fake_start_stop_invalid_state(self, context, instance):
    raise exception.InstanceInvalidState(
        instance_uuid=instance['uuid'], attr='fake_attr',
        method='fake_method', state='fake_state')


def fake_instance_get_by_uuid_not_found(context, uuid,
                                        columns_to_join, use_slave=False):
    raise exception.InstanceNotFound(instance_id=uuid)


class MockSetAdminPassword(object):
    def __init__(self):
        self.instance_id = None
        self.password = None

    def __call__(self, context, instance_id, password):
        self.instance_id = instance_id
        self.password = password


class Base64ValidationTest(test.TestCase):
    def setUp(self):
        super(Base64ValidationTest, self).setUp()
        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)

    def test_decode_base64(self):
        value = "A random string"
        result = self.controller._decode_base64(base64.b64encode(value))
        self.assertEqual(result, value)

    def test_decode_base64_binary(self):
        value = "\x00\x12\x75\x99"
        result = self.controller._decode_base64(base64.b64encode(value))
        self.assertEqual(result, value)

    def test_decode_base64_whitespace(self):
        value = "A random string"
        encoded = base64.b64encode(value)
        white = "\n \n%s\t%s\n" % (encoded[:2], encoded[2:])
        result = self.controller._decode_base64(white)
        self.assertEqual(result, value)

    def test_decode_base64_invalid(self):
        invalid = "A random string"
        result = self.controller._decode_base64(invalid)
        self.assertIsNone(result)

    def test_decode_base64_illegal_bytes(self):
        value = "A random string"
        encoded = base64.b64encode(value)
        white = ">\x01%s*%s()" % (encoded[:2], encoded[2:])
        result = self.controller._decode_base64(white)
        self.assertIsNone(result)


class NeutronV2Subclass(neutron_api.API):
    """Used to ensure that API handles subclasses properly."""
    pass


class ControllerTest(test.TestCase):

    def setUp(self):
        super(ControllerTest, self).setUp()
        self.flags(verbose=True, use_ipv6=False)
        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fake.stub_out_image_service(self.stubs)
        return_server = fakes.fake_instance_get()
        return_servers = fakes.fake_instance_get_all_by_filters()
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers)
        self.stubs.Set(db, 'instance_get_by_uuid',
                       return_server)
        self.stubs.Set(db, 'instance_update_and_get_original',
                       instance_update_and_get_original)

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)
        self.ips_controller = ips.IPsController()
        policy.reset()
        policy.init()
        fake_network.stub_out_nw_api_get_instance_nw_info(self.stubs)


class ServersControllerTest(ControllerTest):

    def setUp(self):
        super(ServersControllerTest, self).setUp()
        CONF.set_override('glance_host', 'localhost')
        nova_utils.reset_is_neutron()

    def test_requested_networks_prefix(self):
        uuid = 'br-00000000-0000-0000-0000-000000000000'
        requested_networks = [{'uuid': uuid}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertIn((uuid, None), res)

    def test_requested_networks_neutronv2_enabled_with_port(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_requested_networks_neutronv2_enabled_with_network(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        requested_networks = [{'uuid': network}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(network, None, None)])

    def test_requested_networks_neutronv2_enabled_with_network_and_port(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_requested_networks_neutronv2_enabled_conflict_on_fixed_ip(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        addr = '10.0.0.1'
        requested_networks = [{'uuid': network,
                               'fixed_ip': addr,
                               'port': port}]
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller._get_requested_networks,
            requested_networks)

    def test_requested_networks_neutronv2_disabled_with_port(self):
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port}]
        self.assertRaises(
            webob.exc.HTTPBadRequest,
            self.controller._get_requested_networks,
            requested_networks)

    def test_requested_networks_api_enabled_with_v2_subclass(self):
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_requested_networks_neutronv2_subclass_with_port(self):
        cls = 'nova.tests.api.openstack.compute.test_servers.NeutronV2Subclass'
        self.flags(network_api_class=cls)
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port}]
        res = self.controller._get_requested_networks(requested_networks)
        self.assertEqual(res, [(None, None, port)])

    def test_get_server_by_uuid(self):
        req = fakes.HTTPRequestV3.blank('/servers/%s' % FAKE_UUID)
        res_dict = self.controller.show(req, FAKE_UUID)
        self.assertEqual(res_dict['server']['id'], FAKE_UUID)

    def test_get_server_joins_pci_devices(self):
        self.expected_attrs = None

        def fake_get(_self, *args, **kwargs):
            self.expected_attrs = kwargs['expected_attrs']
            ctxt = context.RequestContext('fake', 'fake')
            return fake_instance.fake_instance_obj(ctxt)

        self.stubs.Set(compute_api.API, 'get', fake_get)

        req = fakes.HTTPRequestV3.blank('/servers/%s' % FAKE_UUID)
        self.controller.show(req, FAKE_UUID)

        self.assertIn('pci_devices', self.expected_attrs)

    def test_unique_host_id(self):
        """Create two servers with the same host and different
        project_ids and check that the host_id's are unique.
        """
        def return_instance_with_host(self, *args, **kwargs):
            project_id = str(uuid.uuid4())
            return fakes.stub_instance(id=1, uuid=FAKE_UUID,
                                       project_id=project_id,
                                       host='fake_host')

        self.stubs.Set(db, 'instance_get_by_uuid',
                       return_instance_with_host)
        self.stubs.Set(db, 'instance_get',
                       return_instance_with_host)

        req = fakes.HTTPRequestV3.blank('/servers/%s' % FAKE_UUID)
        server1 = self.controller.show(req, FAKE_UUID)
        server2 = self.controller.show(req, FAKE_UUID)

        self.assertNotEqual(server1['server']['host_id'],
                            server2['server']['host_id'])

    def _get_server_data_dict(self, uuid, image_bookmark, flavor_bookmark,
                              status="ACTIVE", progress=100):
        return {
            "server": {
                "id": uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": progress,
                "name": "server1",
                "status": status,
                "host_id": '',
                "image": {
                    "id": "10",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                      {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'}
                    ]
                },
                "metadata": {
                    "seq": "1",
                },
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v3/servers/%s" % uuid,
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/%s" % uuid,
                    },
                ],
            }
        }

    def test_get_server_by_id(self):
        self.flags(use_ipv6=True)
        image_bookmark = "http://localhost:9292/images/10"
        flavor_bookmark = "http://localhost/flavors/1"

        uuid = FAKE_UUID
        req = fakes.HTTPRequestV3.blank('/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)

        expected_server = self._get_server_data_dict(uuid,
                                                     image_bookmark,
                                                     flavor_bookmark,
                                                     status="BUILD",
                                                     progress=0)

        self.assertThat(res_dict, matchers.DictMatches(expected_server))

    def test_get_server_with_active_status_by_id(self):
        image_bookmark = "http://localhost:9292/images/10"
        flavor_bookmark = "http://localhost/flavors/1"

        new_return_server = fakes.fake_instance_get(
                vm_state=vm_states.ACTIVE, progress=100)
        self.stubs.Set(db, 'instance_get_by_uuid', new_return_server)

        uuid = FAKE_UUID
        req = fakes.HTTPRequestV3.blank('/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        expected_server = self._get_server_data_dict(uuid,
                                                     image_bookmark,
                                                     flavor_bookmark)
        self.assertThat(res_dict, matchers.DictMatches(expected_server))

    def test_get_server_with_id_image_ref_by_id(self):
        image_ref = "10"
        image_bookmark = "http://localhost:9292/images/10"
        flavor_id = "1"
        flavor_bookmark = "http://localhost/flavors/1"

        new_return_server = fakes.fake_instance_get(
                vm_state=vm_states.ACTIVE, image_ref=image_ref,
                flavor_id=flavor_id, progress=100)
        self.stubs.Set(db, 'instance_get_by_uuid', new_return_server)

        uuid = FAKE_UUID
        req = fakes.HTTPRequestV3.blank('/servers/%s' % uuid)
        res_dict = self.controller.show(req, uuid)
        expected_server = self._get_server_data_dict(uuid,
                                                     image_bookmark,
                                                     flavor_bookmark)

        self.assertThat(res_dict, matchers.DictMatches(expected_server))

    def test_get_server_addresses_from_cache(self):
        pub0 = ('172.19.0.1', '172.19.0.2',)
        pub1 = ('1.2.3.4',)
        pub2 = ('b33f::fdee:ddff:fecc:bbaa',)
        priv0 = ('192.168.0.3', '192.168.0.4',)

        def _ip(ip):
            return {'address': ip, 'type': 'fixed'}

        nw_cache = [
            {'address': 'aa:aa:aa:aa:aa:aa',
             'id': 1,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'public',
                         'subnets': [{'cidr': '172.19.0.0/24',
                                      'ips': [_ip(ip) for ip in pub0]},
                                      {'cidr': '1.2.3.0/16',
                                       'ips': [_ip(ip) for ip in pub1]},
                                      {'cidr': 'b33f::/64',
                                       'ips': [_ip(ip) for ip in pub2]}]}},
            {'address': 'bb:bb:bb:bb:bb:bb',
             'id': 2,
             'network': {'bridge': 'br1',
                         'id': 2,
                         'label': 'private',
                         'subnets': [{'cidr': '192.168.0.0/24',
                                      'ips': [_ip(ip) for ip in priv0]}]}}]

        return_server = fakes.fake_instance_get(nw_cache=nw_cache)
        self.stubs.Set(db, 'instance_get_by_uuid', return_server)

        req = fakes.HTTPRequestV3.blank('/servers/%s/ips' % FAKE_UUID)
        res_dict = self.ips_controller.index(req, FAKE_UUID)

        expected = {
            'addresses': {
                'private': [
                    {'version': 4, 'addr': '192.168.0.3',
                     'type': 'fixed', 'mac_addr': 'bb:bb:bb:bb:bb:bb'},
                    {'version': 4, 'addr': '192.168.0.4',
                     'type': 'fixed', 'mac_addr': 'bb:bb:bb:bb:bb:bb'},
                ],
                'public': [
                    {'version': 4, 'addr': '172.19.0.1',
                     'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 4, 'addr': '172.19.0.2',
                     'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 4, 'addr': '1.2.3.4',
                     'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    {'version': 6, 'addr': 'b33f::fdee:ddff:fecc:bbaa',
                     'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                ],
            },
        }
        self.assertThat(res_dict, matchers.DictMatches(expected))

    def test_get_server_addresses_nonexistent_network(self):
        url = '/v3/servers/%s/ips/network_0' % FAKE_UUID
        req = fakes.HTTPRequestV3.blank(url)
        self.assertRaises(webob.exc.HTTPNotFound, self.ips_controller.show,
                          req, FAKE_UUID, 'network_0')

    def test_get_server_addresses_nonexistent_server(self):
        def fake_instance_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(db, 'instance_get_by_uuid', fake_instance_get)

        server_id = str(uuid.uuid4())
        req = fakes.HTTPRequestV3.blank('/servers/%s/ips' % server_id)
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.ips_controller.index, req, server_id)

    def test_get_server_list_empty(self):
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers_empty)

        req = fakes.HTTPRequestV3.blank('/servers')
        res_dict = self.controller.index(req)

        num_servers = len(res_dict['servers'])
        self.assertEqual(0, num_servers)

    def test_get_server_list_with_reservation_id(self):
        req = fakes.HTTPRequestV3.blank('/servers?reservation_id=foo')
        res_dict = self.controller.index(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_empty(self):
        req = fakes.HTTPRequestV3.blank('/servers/detail?'
                                      'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list_with_reservation_id_details(self):
        req = fakes.HTTPRequestV3.blank('/servers/detail?'
                                      'reservation_id=foo')
        res_dict = self.controller.detail(req)

        i = 0
        for s in res_dict['servers']:
            self.assertEqual(s.get('name'), 'server%d' % (i + 1))
            i += 1

    def test_get_server_list(self):
        req = fakes.HTTPRequestV3.blank('/servers')
        res_dict = self.controller.index(req)

        self.assertEqual(len(res_dict['servers']), 5)
        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['name'], 'server%d' % (i + 1))
            self.assertIsNone(s.get('image', None))

            expected_links = [
                {
                    "rel": "self",
                    "href": "http://localhost/v3/servers/%s" % s['id'],
                },
                {
                    "rel": "bookmark",
                    "href": "http://localhost/servers/%s" % s['id'],
                },
            ]

            self.assertEqual(s['links'], expected_links)

    def test_get_servers_with_limit(self):
        req = fakes.HTTPRequestV3.blank('/servers?limit=3')
        res_dict = self.controller.index(req)

        servers = res_dict['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in xrange(len(servers))])

        servers_links = res_dict['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')
        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual('/v3/servers', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected_params = {'limit': ['3'],
                           'marker': [fakes.get_fake_uuid(2)]}
        self.assertThat(params, matchers.DictMatches(expected_params))

    def test_get_servers_with_limit_bad_value(self):
        req = fakes.HTTPRequestV3.blank('/servers?limit=aaa')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_server_details_empty(self):
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers_empty)

        req = fakes.HTTPRequestV3.blank('/servers/detail')
        res_dict = self.controller.detail(req)

        num_servers = len(res_dict['servers'])
        self.assertEqual(0, num_servers)

    def test_get_server_details_with_limit(self):
        req = fakes.HTTPRequestV3.blank('/servers/detail?limit=3')
        res = self.controller.detail(req)

        servers = res['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in xrange(len(servers))])

        servers_links = res['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual('/v3/servers', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected = {'limit': ['3'], 'marker': [fakes.get_fake_uuid(2)]}
        self.assertThat(params, matchers.DictMatches(expected))

    def test_get_server_details_with_limit_bad_value(self):
        req = fakes.HTTPRequestV3.blank('/servers/detail?limit=aaa')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.detail, req)

    def test_get_server_details_with_limit_and_other_params(self):
        req = fakes.HTTPRequestV3.blank('/servers/detail'
                                      '?limit=3&blah=2:t')
        res = self.controller.detail(req)

        servers = res['servers']
        self.assertEqual([s['id'] for s in servers],
                [fakes.get_fake_uuid(i) for i in xrange(len(servers))])

        servers_links = res['servers_links']
        self.assertEqual(servers_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(servers_links[0]['href'])
        self.assertEqual('/v3/servers', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        expected = {'limit': ['3'], 'blah': ['2:t'],
                    'marker': [fakes.get_fake_uuid(2)]}
        self.assertThat(params, matchers.DictMatches(expected))

    def test_get_servers_with_too_big_limit(self):
        req = fakes.HTTPRequestV3.blank('/servers?limit=30')
        res_dict = self.controller.index(req)
        self.assertNotIn('servers_links', res_dict)

    def test_get_servers_with_bad_limit(self):
        req = fakes.HTTPRequestV3.blank('/servers?limit=asdf')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_servers_with_marker(self):
        url = '/v3/servers?marker=%s' % fakes.get_fake_uuid(2)
        req = fakes.HTTPRequestV3.blank(url)
        servers = self.controller.index(req)['servers']
        self.assertEqual([s['name'] for s in servers], ["server4", "server5"])

    def test_get_servers_with_limit_and_marker(self):
        url = '/v3/servers?limit=2&marker=%s' % fakes.get_fake_uuid(1)
        req = fakes.HTTPRequestV3.blank(url)
        servers = self.controller.index(req)['servers']
        self.assertEqual([s['name'] for s in servers], ['server3', 'server4'])

    def test_get_servers_with_bad_marker(self):
        req = fakes.HTTPRequestV3.blank('/servers?limit=2&marker=asdf')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_servers_with_bad_option(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?unknownoption=whee')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_image(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('image', search_opts)
            self.assertEqual(search_opts['image'], '12345')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?image=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_tenant_id_filter_converts_to_project_id_for_admin(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertIsNotNone(filters)
            self.assertEqual(filters['project_id'], 'newfake')
            self.assertFalse(filters.get('tenant_id'))
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers'
                                     '?all_tenants=1&tenant_id=newfake',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_tenant_id_filter_no_admin_context(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertNotEqual(filters, None)
            self.assertEqual(filters['project_id'], 'fake')
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?tenant_id=newfake')
        res = self.controller.index(req)
        self.assertTrue('servers' in res)

    def test_tenant_id_filter_implies_all_tenants(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertNotEqual(filters, None)
            # The project_id assertion checks that the project_id
            # filter is set to that specified in the request url and
            # not that of the context, verifying that the all_tenants
            # flag was enabled
            self.assertEqual(filters['project_id'], 'newfake')
            self.assertFalse(filters.get('tenant_id'))
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?tenant_id=newfake',
                                      use_admin_context=True)
        res = self.controller.index(req)
        self.assertTrue('servers' in res)

    def test_all_tenants_param_normal(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertNotIn('project_id', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?all_tenants',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_one(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertNotIn('project_id', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?all_tenants=1',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_zero(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertNotIn('all_tenants', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?all_tenants=0',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_false(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertNotIn('all_tenants', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?all_tenants=false',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_param_invalid(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None,
                         expected_attrs=[]):
            self.assertNotIn('all_tenants', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?all_tenants=xxx',
                                      use_admin_context=True)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_admin_restricted_tenant(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertIsNotNone(filters)
            self.assertEqual(filters['project_id'], 'fake')
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers',
                                      use_admin_context=True)
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_pass_policy(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None, use_slave=False,
                         expected_attrs=[]):
            self.assertIsNotNone(filters)
            self.assertNotIn('project_id', filters)
            return [fakes.stub_instance(100)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        rules = {
            "compute:get_all_tenants":
                common_policy.parse_rule("project_id:fake"),
            "compute:get_all":
                common_policy.parse_rule("project_id:fake"),
        }

        common_policy.set_rules(common_policy.Rules(rules))

        req = fakes.HTTPRequestV3.blank('/servers?all_tenants=1')
        res = self.controller.index(req)

        self.assertIn('servers', res)

    def test_all_tenants_fail_policy(self):
        def fake_get_all(context, filters=None, sort_key=None,
                         sort_dir='desc', limit=None, marker=None,
                         columns_to_join=None):
            self.assertIsNotNone(filters)
            return [fakes.stub_instance(100)]

        rules = {
            "compute:get_all_tenants":
                common_policy.parse_rule("project_id:non_fake"),
            "compute:get_all":
                common_policy.parse_rule("project_id:fake"),
        }

        common_policy.set_rules(common_policy.Rules(rules))
        self.stubs.Set(db, 'instance_get_all_by_filters',
                       fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?all_tenants=1')
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.index, req)

    def test_get_servers_allows_flavor(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('flavor', search_opts)
            # flavor is an integer ID
            self.assertEqual(search_opts['flavor'], '12345')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?flavor=12345')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_with_bad_flavor(self):
        req = fakes.HTTPRequestV3.blank('/servers?flavor=abcde')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 0)

    def test_get_server_details_with_bad_flavor(self):
        req = fakes.HTTPRequestV3.blank('/servers?flavor=abcde')
        servers = self.controller.detail(req)['servers']

        self.assertThat(servers, testtools.matchers.HasLength(0))

    def test_get_servers_allows_status(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'], [vm_states.ACTIVE])
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?status=active')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_task_status(self):
        server_uuid = str(uuid.uuid4())
        task_state = task_states.REBOOTING

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('task_state', search_opts)
            self.assertEqual([task_states.REBOOT_PENDING,
                              task_states.REBOOT_STARTED,
                              task_states.REBOOTING],
                             search_opts['task_state'])
            db_list = [fakes.stub_instance(100, uuid=server_uuid,
                                                task_state=task_state)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?status=reboot')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_resize_status(self):
        # Test when resize status, it maps list of vm states.
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'],
                             [vm_states.ACTIVE, vm_states.STOPPED])

            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?status=resize')

        servers = self.controller.detail(req)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_invalid_status(self):
        # Test getting servers by invalid status.
        req = fakes.HTTPRequestV3.blank('/servers?status=baloney',
                                      use_admin_context=False)
        servers = self.controller.index(req)['servers']
        self.assertEqual(len(servers), 0)

    def test_get_servers_deleted_status_as_user(self):
        req = fakes.HTTPRequestV3.blank('/servers?status=deleted',
                                      use_admin_context=False)
        self.assertRaises(webob.exc.HTTPForbidden,
                          self.controller.detail, req)

    def test_get_servers_deleted_status_as_admin(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIn('vm_state', search_opts)
            self.assertEqual(search_opts['vm_state'], ['deleted'])

            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?status=deleted',
                                      use_admin_context=True)

        servers = self.controller.detail(req)['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_name(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('name', search_opts)
            self.assertEqual(search_opts['name'], 'whee.*')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?name=whee.*')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_changes_since(self):
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('changes-since', search_opts)
            changes_since = datetime.datetime(2011, 1, 24, 17, 8, 1,
                                              tzinfo=iso8601.iso8601.UTC)
            self.assertEqual(search_opts['changes-since'], changes_since)
            self.assertNotIn('deleted', search_opts)
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        params = 'changes_since=2011-01-24T17:08:01Z'
        req = fakes.HTTPRequestV3.blank('/servers?%s' % params)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_changes_since_bad_value(self):
        params = 'changes_since=asdf'
        req = fakes.HTTPRequestV3.blank('/servers?%s' % params)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.index, req)

    def test_get_servers_admin_filters_as_user(self):
        """Test getting servers by admin-only or unknown options when
        context is not admin. Make sure the admin and unknown options
        are stripped before they get to compute_api.get_all()
        """
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            # Allowed by user
            self.assertIn('name', search_opts)
            self.assertIn('ip', search_opts)
            # OSAPI converts status to vm_state
            self.assertIn('vm_state', search_opts)
            # Allowed only by admins with admin API on
            self.assertNotIn('unknown_option', search_opts)
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = fakes.HTTPRequest.blank('/servers?%s' % query_str)
        res = self.controller.index(req)

        servers = res['servers']
        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_admin_options_as_admin(self):
        """Test getting servers by admin-only or unknown options when
        context is admin. All options should be passed
        """
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            # Allowed by user
            self.assertIn('name', search_opts)
            # OSAPI converts status to vm_state
            self.assertIn('vm_state', search_opts)
            # Allowed only by admins with admin API on
            self.assertIn('ip', search_opts)
            self.assertIn('unknown_option', search_opts)
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        query_str = "name=foo&ip=10.*&status=active&unknown_option=meow"
        req = fakes.HTTPRequestV3.blank('/servers?%s' % query_str,
                                      use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_allows_ip(self):
        """Test getting servers by ip."""

        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('ip', search_opts)
            self.assertEqual(search_opts['ip'], '10\..*')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?ip=10\..*')
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_servers_admin_allows_ip6(self):
        """Test getting servers by ip6 with admin_api enabled and
        admin context
        """
        server_uuid = str(uuid.uuid4())

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.assertIsNotNone(search_opts)
            self.assertIn('ip6', search_opts)
            self.assertEqual(search_opts['ip6'], 'ffff.*')
            db_list = [fakes.stub_instance(100, uuid=server_uuid)]
            return instance_obj._make_instance_list(
                context, instance_obj.InstanceList(), db_list, FIELDS)

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers?ip6=ffff.*',
                                      use_admin_context=True)
        servers = self.controller.index(req)['servers']

        self.assertEqual(len(servers), 1)
        self.assertEqual(servers[0]['id'], server_uuid)

    def test_get_all_server_details(self):
        expected_flavor = {
                "id": "1",
                "links": [
                    {
                        "rel": "bookmark",
                        "href": 'http://localhost/flavors/1',
                        },
                    ],
                }
        expected_image = {
            "id": "10",
            "links": [
                {
                    "rel": "bookmark",
                    "href": 'http://localhost:9292/images/10',
                    },
                ],
            }
        req = fakes.HTTPRequestV3.blank('/servers/detail')
        res_dict = self.controller.detail(req)

        for i, s in enumerate(res_dict['servers']):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['host_id'], '')
            self.assertEqual(s['name'], 'server%d' % (i + 1))
            self.assertEqual(s['image'], expected_image)
            self.assertEqual(s['flavor'], expected_flavor)
            self.assertEqual(s['status'], 'BUILD')
            self.assertEqual(s['metadata']['seq'], str(i + 1))

    def test_get_all_server_details_with_host(self):
        """We want to make sure that if two instances are on the same host,
        then they return the same host_id. If two instances are on different
        hosts, they should return different host_ids. In this test,
        there are 5 instances - 2 on one host and 3 on another.
        """

        def return_servers_with_host(context, *args, **kwargs):
            return [fakes.stub_instance(i + 1, 'fake', 'fake', host=i % 2,
                                        uuid=fakes.get_fake_uuid(i))
                    for i in xrange(5)]

        self.stubs.Set(db, 'instance_get_all_by_filters',
                       return_servers_with_host)

        req = fakes.HTTPRequestV3.blank('/servers/detail')
        res_dict = self.controller.detail(req)

        server_list = res_dict['servers']
        host_ids = [server_list[0]['host_id'], server_list[1]['host_id']]
        self.assertTrue(host_ids[0] and host_ids[1])
        self.assertNotEqual(host_ids[0], host_ids[1])

        for i, s in enumerate(server_list):
            self.assertEqual(s['id'], fakes.get_fake_uuid(i))
            self.assertEqual(s['host_id'], host_ids[i % 2])
            self.assertEqual(s['name'], 'server%d' % (i + 1))

    def test_get_servers_joins_pci_devices(self):
        self.expected_attrs = None

        def fake_get_all(compute_self, context, search_opts=None,
                         sort_key=None, sort_dir='desc',
                         limit=None, marker=None, want_objects=False,
                         expected_attrs=[]):
            self.expected_attrs = expected_attrs
            return []

        self.stubs.Set(compute_api.API, 'get_all', fake_get_all)

        req = fakes.HTTPRequestV3.blank('/servers', use_admin_context=True)
        servers = self.controller.index(req)['servers']
        self.assertIn('pci_devices', self.expected_attrs)


class ServersControllerDeleteTest(ControllerTest):

    def setUp(self):
        super(ServersControllerDeleteTest, self).setUp()
        self.server_delete_called = False

        def instance_destroy_mock(*args, **kwargs):
            self.server_delete_called = True
            deleted_at = timeutils.utcnow()
            return fake_instance.fake_db_instance(deleted_at=deleted_at)

        self.stubs.Set(db, 'instance_destroy', instance_destroy_mock)

    def _create_delete_request(self, uuid):
        fakes.stub_out_instance_quota(self.stubs, 0, 10)
        req = fakes.HTTPRequestV3.blank('/servers/%s' % uuid)
        req.method = 'DELETE'
        return req

    def _delete_server_instance(self, uuid=FAKE_UUID):
        req = self._create_delete_request(uuid)
        self.stubs.Set(db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        self.controller.delete(req, uuid)

    def test_delete_server_instance(self):
        self._delete_server_instance()
        self.assertTrue(self.server_delete_called)

    def test_delete_server_instance_not_found(self):
        self.assertRaises(webob.exc.HTTPNotFound,
                          self._delete_server_instance,
                          uuid='non-existent-uuid')

    def test_delete_server_instance_while_building(self):
        req = self._create_delete_request(FAKE_UUID)
        self.controller.delete(req, FAKE_UUID)

        self.assertTrue(self.server_delete_called)

    def test_delete_locked_server(self):
        req = self._create_delete_request(FAKE_UUID)
        self.stubs.Set(compute_api.API, 'soft_delete',
                       fakes.fake_actions_to_locked_server)
        self.stubs.Set(compute_api.API, 'delete',
                       fakes.fake_actions_to_locked_server)

        self.assertRaises(webob.exc.HTTPConflict, self.controller.delete,
                          req, FAKE_UUID)

    def test_delete_server_instance_while_resize(self):
        req = self._create_delete_request(FAKE_UUID)
        self.stubs.Set(db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_states.ACTIVE,
                                        task_state=task_states.RESIZE_PREP))

        self.controller.delete(req, FAKE_UUID)
        # Delete shoud be allowed in any case, even during resizing,
        # because it may get stuck.
        self.assertTrue(self.server_delete_called)

    def test_delete_server_instance_if_not_launched(self):
        self.flags(reclaim_instance_interval=3600)
        req = fakes.HTTPRequestV3.blank('/servers/%s' % FAKE_UUID)
        req.method = 'DELETE'

        self.server_delete_called = False

        self.stubs.Set(db, 'instance_get_by_uuid',
            fakes.fake_instance_get(launched_at=None))

        def instance_destroy_mock(*args, **kwargs):
            self.server_delete_called = True
            deleted_at = timeutils.utcnow()
            return fake_instance.fake_db_instance(deleted_at=deleted_at)
        self.stubs.Set(db, 'instance_destroy', instance_destroy_mock)

        self.controller.delete(req, FAKE_UUID)
        # delete() should be called for instance which has never been active,
        # even if reclaim_instance_interval has been set.
        self.assertEqual(self.server_delete_called, True)


class ServersControllerRebuildInstanceTest(ControllerTest):

    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    image_href = 'http://localhost/v3/fake/images/%s' % image_uuid

    def setUp(self):
        super(ServersControllerRebuildInstanceTest, self).setUp()
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fakes.fake_instance_get(vm_state=vm_states.ACTIVE))
        self.body = {
            'rebuild': {
                'name': 'new_name',
                'image_ref': self.image_href,
                'metadata': {
                    'open': 'stack',
                },
            },
        }
        self.req = fakes.HTTPRequest.blank('/fake/servers/a/action')
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"

    def test_rebuild_instance_with_blank_metadata_key(self):
        self.body['rebuild']['metadata'][''] = 'world'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_with_metadata_key_too_long(self):
        self.body['rebuild']['metadata'][('a' * 260)] = 'world'

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_with_metadata_value_too_long(self):
        self.body['rebuild']['metadata']['key1'] = ('a' * 260)

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller._action_rebuild, self.req,
                          FAKE_UUID, body=self.body)

    def test_rebuild_instance_fails_when_min_ram_too_small(self):
        # make min_ram larger than our instance ram size
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='active', properties={'key1': 'value1'},
                        min_ram="4096", min_disk="10")

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_fails_when_min_disk_too_small(self):
        # make min_disk larger than our instance disk size
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='active', properties={'key1': 'value1'},
                        min_ram="128", min_disk="100000")

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild, self.req,
                          FAKE_UUID, body=self.body)

    def test_rebuild_instance_image_too_large(self):
        # make image size larger than our instance disk size
        size = str(1000 * (1024 ** 3))

        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='active', size=size)

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_name_all_blank(self):
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True, status='active')

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)
        self.body['rebuild']['name'] = '     '
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_rebuild_instance_with_deleted_image(self):
        def fake_get_image(self, context, image_href):
            return dict(id='76fa36fc-c930-4bf3-8c8a-ea2a2420deb6',
                        name='public image', is_public=True,
                        status='DELETED')

        self.stubs.Set(fake._FakeImageService, 'show', fake_get_image)

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller._action_rebuild,
                          self.req, FAKE_UUID, body=self.body)

    def test_start(self):
        self.mox.StubOutWithMock(compute_api.API, 'start')
        compute_api.API.start(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(start="")
        self.controller._start_server(req, FAKE_UUID, body)

    def test_start_policy_failed(self):
        rules = {
            "compute:v3:servers:start":
                common_policy.parse_rule("project_id:non_fake")
        }
        common_policy.set_rules(common_policy.Rules(rules))
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(start="")
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._start_server,
                                req, FAKE_UUID, body)
        self.assertIn("compute:v3:servers:start", exc.format_message())

    def test_start_not_ready(self):
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_not_ready)
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, FAKE_UUID, body)

    def test_start_locked_server(self):
        self.stubs.Set(compute_api.API, 'start',
                       fakes.fake_actions_to_locked_server)
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, FAKE_UUID, body)

    def test_start_invalid(self):
        self.stubs.Set(compute_api.API, 'start', fake_start_stop_invalid_state)
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._start_server, req, FAKE_UUID, body)

    def test_stop(self):
        self.mox.StubOutWithMock(compute_api.API, 'stop')
        compute_api.API.stop(mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()

        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(stop="")
        self.controller._stop_server(req, FAKE_UUID, body)

    def test_stop_policy_failed(self):
        rules = {
            "compute:v3:servers:stop":
                common_policy.parse_rule("project_id:non_fake")
        }
        common_policy.set_rules(common_policy.Rules(rules))
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(stop='')
        exc = self.assertRaises(exception.PolicyNotAuthorized,
                                self.controller._stop_server,
                                req, FAKE_UUID, body)
        self.assertIn("compute:v3:servers:stop", exc.format_message())

    def test_stop_not_ready(self):
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_not_ready)
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, FAKE_UUID, body)

    def test_stop_locked_server(self):
        self.stubs.Set(compute_api.API, 'stop',
                       fakes.fake_actions_to_locked_server)
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, FAKE_UUID, body)

    def test_stop_invalid_state(self):
        self.stubs.Set(compute_api.API, 'stop', fake_start_stop_invalid_state)
        req = fakes.HTTPRequestV3.blank('/servers/%s/action' % FAKE_UUID)
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPConflict,
            self.controller._stop_server, req, FAKE_UUID, body)

    def test_start_with_bogus_id(self):
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid_not_found)
        req = fakes.HTTPRequestV3.blank('/servers/test_inst/action')
        body = dict(start="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._start_server, req, 'test_inst', body)

    def test_stop_with_bogus_id(self):
        self.stubs.Set(db, 'instance_get_by_uuid',
                       fake_instance_get_by_uuid_not_found)
        req = fakes.HTTPRequestV3.blank('/servers/test_inst/action')
        body = dict(stop="")
        self.assertRaises(webob.exc.HTTPNotFound,
            self.controller._stop_server, req, 'test_inst', body)


class ServersControllerUpdateTest(ControllerTest):

    def _get_request(self, body=None, options=None):
        if options:
            self.stubs.Set(db, 'instance_get',
                           fakes.fake_instance_get(**options))
        req = fakes.HTTPRequestV3.blank('/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        req.body = jsonutils.dumps(body)
        return req

    def test_update_server_all_attributes(self):
        body = {'server': {
                  'name': 'server_test',
               }}
        req = self._get_request(body, {'name': 'server_test'})
        res_dict = self.controller.update(req, FAKE_UUID, body=body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_name(self):
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body, {'name': 'server_test'})
        res_dict = self.controller.update(req, FAKE_UUID, body=body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_name_too_long(self):
        body = {'server': {'name': 'x' * 256}}
        req = self._get_request(body, {'name': 'server_test'})
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                            req, FAKE_UUID, body=body)

    def test_update_server_name_all_blank_spaces(self):
        self.stubs.Set(db, 'instance_get',
                fakes.fake_instance_get(name='server_test'))
        req = fakes.HTTPRequest.blank('/v3/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'server': {'name': ' ' * 64}}
        req.body = jsonutils.dumps(body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_adminPass_ignored(self):
        inst_dict = dict(name='server_test', adminPass='bacon')
        body = dict(server=inst_dict)

        def server_update(context, id, params):
            filtered_dict = {
                'display_name': 'server_test',
            }
            self.assertEqual(params, filtered_dict)
            filtered_dict['uuid'] = id
            return filtered_dict

        self.stubs.Set(db, 'instance_update', server_update)
        # FIXME (comstud)
        #        self.stubs.Set(db, 'instance_get',
        #                return_server_with_attributes(name='server_test'))

        req = fakes.HTTPRequest.blank('/fake/servers/%s' % FAKE_UUID)
        req.method = 'PUT'
        req.content_type = "application/json"
        req.body = jsonutils.dumps(body)
        res_dict = self.controller.update(req, FAKE_UUID, body=body)

        self.assertEqual(res_dict['server']['id'], FAKE_UUID)
        self.assertEqual(res_dict['server']['name'], 'server_test')

    def test_update_server_not_found(self):
        def fake_get(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(compute_api.API, 'get', fake_get)
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_not_found_on_update(self):
        def fake_update(*args, **kwargs):
            raise exception.InstanceNotFound(instance_id='fake')

        self.stubs.Set(db, 'instance_update_and_get_original', fake_update)
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body)
        self.assertRaises(webob.exc.HTTPNotFound, self.controller.update,
                          req, FAKE_UUID, body=body)

    def test_update_server_policy_fail(self):
        rule = {'compute:update': common_policy.parse_rule('role:admin')}
        common_policy.set_rules(common_policy.Rules(rule))
        body = {'server': {'name': 'server_test'}}
        req = self._get_request(body, {'name': 'server_test'})
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller.update, req, FAKE_UUID, body=body)


class ServerStatusTest(test.TestCase):

    def setUp(self):
        super(ServerStatusTest, self).setUp()
        fakes.stub_out_nw_api(self.stubs)

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)

    def _get_with_state(self, vm_state, task_state=None):
        self.stubs.Set(db, 'instance_get_by_uuid',
                fakes.fake_instance_get(vm_state=vm_state,
                                        task_state=task_state))

        request = fakes.HTTPRequestV3.blank('/servers/%s' % FAKE_UUID)
        return self.controller.show(request, FAKE_UUID)

    def test_active(self):
        response = self._get_with_state(vm_states.ACTIVE)
        self.assertEqual(response['server']['status'], 'ACTIVE')

    def test_reboot(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBOOTING)
        self.assertEqual(response['server']['status'], 'REBOOT')

    def test_reboot_hard(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBOOTING_HARD)
        self.assertEqual(response['server']['status'], 'HARD_REBOOT')

    def test_reboot_resize_policy_fail(self):
        def fake_get_server(context, req, id):
            return fakes.stub_instance(id)

        self.stubs.Set(self.controller, '_get_server', fake_get_server)

        rule = {'compute:reboot':
                common_policy.parse_rule('role:admin')}
        common_policy.set_rules(common_policy.Rules(rule))
        req = fakes.HTTPRequestV3.blank('/servers/1234/action')
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_reboot, req, '1234',
                {'reboot': {'type': 'HARD'}})

    def test_rebuild(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.REBUILDING)
        self.assertEqual(response['server']['status'], 'REBUILD')

    def test_rebuild_error(self):
        response = self._get_with_state(vm_states.ERROR)
        self.assertEqual(response['server']['status'], 'ERROR')

    def test_resize(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.RESIZE_PREP)
        self.assertEqual(response['server']['status'], 'RESIZE')

    def test_confirm_resize_policy_fail(self):
        def fake_get_server(context, req, id):
            return fakes.stub_instance(id)

        self.stubs.Set(self.controller, '_get_server', fake_get_server)

        rule = {'compute:confirm_resize':
                common_policy.parse_rule('role:admin')}
        common_policy.set_rules(common_policy.Rules(rule))
        req = fakes.HTTPRequestV3.blank('/servers/1234/action')
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_confirm_resize, req, '1234', {})

    def test_verify_resize(self):
        response = self._get_with_state(vm_states.RESIZED, None)
        self.assertEqual(response['server']['status'], 'VERIFY_RESIZE')

    def test_revert_resize(self):
        response = self._get_with_state(vm_states.RESIZED,
                                        task_states.RESIZE_REVERTING)
        self.assertEqual(response['server']['status'], 'REVERT_RESIZE')

    def test_revert_resize_policy_fail(self):
        def fake_get_server(context, req, id):
            return fakes.stub_instance(id)

        self.stubs.Set(self.controller, '_get_server', fake_get_server)

        rule = {'compute:revert_resize':
                common_policy.parse_rule('role:admin')}
        common_policy.set_rules(common_policy.Rules(rule))
        req = fakes.HTTPRequestV3.blank('/servers/1234/action')
        self.assertRaises(exception.PolicyNotAuthorized,
                self.controller._action_revert_resize, req, '1234', {})

    def test_password_update(self):
        response = self._get_with_state(vm_states.ACTIVE,
                                        task_states.UPDATING_PASSWORD)
        self.assertEqual(response['server']['status'], 'PASSWORD')

    def test_stopped(self):
        response = self._get_with_state(vm_states.STOPPED)
        self.assertEqual(response['server']['status'], 'SHUTOFF')


class ServersControllerCreateTest(test.TestCase):
    image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    flavor_ref = 'http://localhost/123/flavors/3'

    def setUp(self):
        """Shared implementation for tests below that create instance."""
        super(ServersControllerCreateTest, self).setUp()

        self.flags(verbose=True,
                   enable_instance_password=True)
        self.instance_cache_num = 0
        self.instance_cache_by_id = {}
        self.instance_cache_by_uuid = {}

        fakes.stub_out_nw_api(self.stubs)

        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)

        def instance_create(context, inst):
            inst_type = flavors.get_flavor_by_flavor_id(3)
            image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
            def_image_ref = 'http://localhost/images/%s' % image_uuid
            self.instance_cache_num += 1
            instance = fake_instance.fake_db_instance(**{
                'id': self.instance_cache_num,
                'display_name': inst['display_name'] or 'test',
                'uuid': FAKE_UUID,
                'instance_type': dict(inst_type),
                'image_ref': inst.get('image_ref', def_image_ref),
                'user_id': 'fake',
                'project_id': 'fake',
                'reservation_id': inst['reservation_id'],
                "created_at": datetime.datetime(2010, 10, 10, 12, 0, 0),
                "updated_at": datetime.datetime(2010, 11, 11, 11, 0, 0),
                "config_drive": None,
                "progress": 0,
                "fixed_ips": [],
                "task_state": "",
                "vm_state": "",
                "root_device_name": inst.get('root_device_name', 'vda'),
            })

            self.instance_cache_by_id[instance['id']] = instance
            self.instance_cache_by_uuid[instance['uuid']] = instance
            return instance

        def instance_get(context, instance_id):
            """Stub for compute/api create() pulling in instance after
            scheduling
            """
            return self.instance_cache_by_id[instance_id]

        def instance_update(context, uuid, values):
            instance = self.instance_cache_by_uuid[uuid]
            instance.update(values)
            return instance

        def server_update(context, instance_uuid, params, update_cells=True):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return inst

        def server_update_and_get_original(
                context, instance_uuid, params, update_cells=False,
                columns_to_join=None):
            inst = self.instance_cache_by_uuid[instance_uuid]
            inst.update(params)
            return (inst, inst)

        def fake_method(*args, **kwargs):
            pass

        def project_get_networks(context, user_id):
            return dict(id='1', host='localhost')

        def queue_get_for(context, *args):
            return 'network_topic'

        fakes.stub_out_rate_limiting(self.stubs)
        fakes.stub_out_key_pair_funcs(self.stubs)
        fake.stub_out_image_service(self.stubs)
        self.stubs.Set(uuid, 'uuid4', fake_gen_uuid)
        self.stubs.Set(db, 'project_get_networks',
                       project_get_networks)
        self.stubs.Set(db, 'instance_create', instance_create)
        self.stubs.Set(db, 'instance_system_metadata_update',
                fake_method)
        self.stubs.Set(db, 'instance_get', instance_get)
        self.stubs.Set(db, 'instance_update', instance_update)
        self.stubs.Set(db, 'instance_update_and_get_original',
                server_update_and_get_original)
        self.stubs.Set(manager.VlanManager, 'allocate_fixed_ip',
                       fake_method)
        self.body = {
            'server': {
                'name': 'server_test',
                'image_ref': self.image_uuid,
                'flavor_ref': self.flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                    },
                },
            }
        self.bdm = [{'delete_on_termination': 1,
                     'device_name': 123,
                     'volume_size': 1,
                     'volume_id': '11111111-1111-1111-1111-111111111111'}]

        self.req = fakes.HTTPRequest.blank('/fake/servers')
        self.req.method = 'POST'
        self.req.headers["content-type"] = "application/json"

    def _check_admin_password_len(self, server_dict):
        """utility function - check server_dict for admin_password length."""
        self.assertEqual(CONF.password_length,
                         len(server_dict["admin_password"]))

    def _check_admin_password_missing(self, server_dict):
        """utility function - check server_dict for admin_password absence."""
        self.assertNotIn("admin_password", server_dict)

    def _test_create_instance(self, flavor=2):
        image_uuid = 'c905cedb-7281-47e4-8a62-f26bc5fc4c77'
        self.body['server']['image_ref'] = image_uuid
        self.body['server']['flavor_ref'] = flavor
        self.req.body = jsonutils.dumps(self.body)
        server = self.controller.create(self.req, body=self.body).obj['server']
        self._check_admin_password_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_private_flavor(self):
        values = {
            'name': 'fake_name',
            'memory_mb': 512,
            'vcpus': 1,
            'root_gb': 10,
            'ephemeral_gb': 10,
            'flavorid': '1324',
            'swap': 0,
            'rxtx_factor': 0.5,
            'vcpu_weight': 1,
            'disabled': False,
            'is_public': False,
        }
        db.flavor_create(context.get_admin_context(), values)
        self.assertRaises(webob.exc.HTTPBadRequest, self._test_create_instance,
                          flavor=1324)

    def test_create_server_bad_image_href(self):
        image_href = 1
        self.body['server']['min_count'] = 1
        self.body['server']['image_ref'] = image_href,
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create,
                          self.req, body=self.body)
    # TODO(cyeoh): bp-v3-api-unittests
    # This needs to be ported to the os-networks extension tests
    # def test_create_server_with_invalid_networks_parameter(self):
    #     self.ext_mgr.extensions = {'os-networks': 'fake'}
    #     image_href = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    #     flavor_ref = 'http://localhost/123/flavors/3'
    #     body = {
    #         'server': {
    #         'name': 'server_test',
    #         'imageRef': image_href,
    #         'flavorRef': flavor_ref,
    #         'networks': {'uuid': '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'},
    #         }
    #     }
    #     req = fakes.HTTPRequest.blank('/v2/fake/servers')
    #     req.method = 'POST'
    #     req.body = jsonutils.dumps(body)
    #     req.headers["content-type"] = "application/json"
    #     self.assertRaises(webob.exc.HTTPBadRequest,
    #                       self.controller.create,
    #                       req,
    #                       body)

    def test_create_server_with_deleted_image(self):
        # Get the fake image service so we can set the status to deleted
        (image_service, image_id) = glance.get_remote_image_service(
                context, '')
        image_service.update(context, self.image_uuid, {'status': 'DELETED'})
        self.addCleanup(image_service.update, context, self.image_uuid,
                        {'status': 'active'})

        self.body['server']['flavor_ref'] = 2
        self.req.body = jsonutils.dumps(self.body)
        with testtools.ExpectedException(
                webob.exc.HTTPBadRequest,
                'Image 76fa36fc-c930-4bf3-8c8a-ea2a2420deb6 is not active.'):
            self.controller.create(self.req, body=self.body)

    def test_create_server_image_too_large(self):
        # Get the fake image service so we can set the status to deleted
        (image_service, image_id) = glance.get_remote_image_service(
                                    context, self.image_uuid)

        image = image_service.show(context, image_id)

        orig_size = image['size']
        new_size = str(1000 * (1024 ** 3))
        image_service.update(context, self.image_uuid, {'size': new_size})

        self.addCleanup(image_service.update, context, self.image_uuid,
                        {'size': orig_size})

        self.body['server']['flavor_ref'] = 2
        self.req.body = jsonutils.dumps(self.body)

        with testtools.ExpectedException(
                webob.exc.HTTPBadRequest,
                "Flavor's disk is too small for requested image."):
            self.controller.create(self.req, body=self.body)

    def test_create_instance_image_ref_is_bookmark(self):
        image_href = 'http://localhost/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_image_ref_is_invalid(self):
        image_uuid = 'this_is_not_a_valid_uuid'
        image_href = 'http://localhost/images/%s' % image_uuid
        flavor_ref = 'http://localhost/flavors/3'
        self.body['server']['image_ref'] = image_href
        self.body['server']['flavor_ref'] = flavor_ref
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_no_key_pair(self):
        fakes.stub_out_key_pair_funcs(self.stubs, have_key_pair=False)
        self._test_create_instance()

    def _test_create_extra(self, params, no_image=False):
        self.body['server']['flavor_ref'] = 2
        if no_image:
            self.body['server'].pop('image_ref', None)
        self.body['server'].update(params)
        self.req.body = jsonutils.dumps(self.body)
        self.req.headers["content-type"] = "application/json"
        self.controller.create(self.req, body=self.body).obj['server']

    # TODO(cyeoh): bp-v3-api-unittests
    # This needs to be ported to the os-keypairs extension tests
    # def test_create_instance_with_keypairs_enabled(self):
    #     self.ext_mgr.extensions = {'os-keypairs': 'fake'}
    #     key_name = 'green'
    #
    #     params = {'key_name': key_name}
    #     old_create = compute_api.API.create
    #
    #     # NOTE(sdague): key pair goes back to the database,
    #     # so we need to stub it out for tests
    #     def key_pair_get(context, user_id, name):
    #         return {'public_key': 'FAKE_KEY',
    #                 'fingerprint': 'FAKE_FINGERPRINT',
    #                 'name': name}
    #
    #     def create(*args, **kwargs):
    #         self.assertEqual(kwargs['key_name'], key_name)
    #         return old_create(*args, **kwargs)
    #
    #     self.stubs.Set(db, 'key_pair_get', key_pair_get)
    #     self.stubs.Set(compute_api.API, 'create', create)
    #     self._test_create_extra(params)
    #
    # TODO(cyeoh): bp-v3-api-unittests
    # This needs to be ported to the os-networks extension tests
    # def test_create_instance_with_networks_enabled(self):
    #     self.ext_mgr.extensions = {'os-networks': 'fake'}
    #     net_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
    #     requested_networks = [{'uuid': net_uuid}]
    #     params = {'networks': requested_networks}
    #     old_create = compute_api.API.create

    #     def create(*args, **kwargs):
    #         result = [('76fa36fc-c930-4bf3-8c8a-ea2a2420deb6', None)]
    #         self.assertEqual(kwargs['requested_networks'], result)
    #         return old_create(*args, **kwargs)

    #     self.stubs.Set(compute_api.API, 'create', create)
    #     self._test_create_extra(params)

    def test_create_instance_with_port_with_no_fixed_ips(self):
        port_id = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'port': port_id}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.PortRequiresFixedIP(port_id=port_id)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_network_with_no_subnet(self):
        network = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.NetworkRequiresSubnet(network_uuid=network)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_non_unique_secgroup_name(self):
        network = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network}]
        params = {'networks': requested_networks,
                  'security_groups': [{'name': 'dup'}, {'name': 'dup'}]}

        def fake_create(*args, **kwargs):
            raise exception.NoUniqueMatch("No Unique match found for ...")

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPConflict,
                          self._test_create_extra, params)

    def test_create_instance_with_networks_disabled_neutronv2(self):
        nova_utils.reset_is_neutron()
        self.flags(network_api_class='nova.network.neutronv2.api.API')
        net_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        requested_networks = [{'uuid': net_uuid}]
        params = {'networks': requested_networks}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            result = [('76fa36fc-c930-4bf3-8c8a-ea2a2420deb6', None,
                       None)]
            self.assertEqual(kwargs['requested_networks'], result)
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_networks_disabled(self):
        net_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        requested_networks = [{'uuid': net_uuid}]
        params = {'networks': requested_networks}
        old_create = compute_api.API.create

        def create(*args, **kwargs):
            self.assertIsNone(kwargs['requested_networks'])
            return old_create(*args, **kwargs)

        self.stubs.Set(compute_api.API, 'create', create)
        self._test_create_extra(params)

    def test_create_instance_with_pass_disabled(self):
        # test with admin passwords disabled See lp bug 921814
        self.flags(enable_instance_password=False)

        # proper local hrefs must start with 'http://localhost/v3/'
        self.flags(enable_instance_password=False)
        image_href = 'http://localhost/v2/fake/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self._check_admin_password_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_name_too_long(self):
        # proper local hrefs must start with 'http://localhost/v3/'
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['name'] = 'X' * 256
        self.body['server']['image_ref'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest, self.controller.create,
                          self.req, body=self.body)

    def test_create_instance_name_all_blank_spaces(self):
        # proper local hrefs must start with 'http://localhost/v2/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/images/%s' % image_uuid
        flavor_ref = 'http://localhost/flavors/3'
        body = {
            'server': {
                'name': ' ' * 64,
                'imageRef': image_href,
                'flavorRef': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
            },
        }

        req = fakes.HTTPRequest.blank('/v3/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body=body)

    def test_create_instance(self):
        # proper local hrefs must start with 'http://localhost/v3/'
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self._check_admin_password_len(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_extension_create_exception(self):
        def fake_keypair_server_create(self, server_dict,
                                       create_kwargs):
            raise KeyError

        self.stubs.Set(keypairs.Keypairs, 'server_create',
                       fake_keypair_server_create)
        # proper local hrefs must start with 'http://localhost/v3/'
        image_uuid = '76fa36fc-c930-4bf3-8c8a-ea2a2420deb6'
        image_href = 'http://localhost/v3/images/%s' % image_uuid
        flavor_ref = 'http://localhost/123/flavors/3'
        body = {
            'server': {
                'name': 'server_test',
                'image_ref': image_href,
                'flavor_ref': flavor_ref,
                'metadata': {
                    'hello': 'world',
                    'open': 'stack',
                },
            },
        }

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.body = jsonutils.dumps(body)
        req.headers["content-type"] = "application/json"
        self.assertRaises(KeyError, self.controller.create, req, body=body)

    def test_create_instance_pass_disabled(self):
        self.flags(enable_instance_password=False)
        # proper local hrefs must start with 'http://localhost/v3/'
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self._check_admin_password_missing(server)
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_too_much_metadata(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.body['server']['metadata']['vote'] = 'fiddletown'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_key_too_long(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.body['server']['metadata'] = {('a' * 260): '12345'}

        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_value_too_long(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.body['server']['metadata'] = {'key1': ('a' * 260)}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPRequestEntityTooLarge,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_key_blank(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.body['server']['metadata'] = {'': 'abcd'}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_not_dict(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.body['server']['metadata'] = 'string'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_key_not_string(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.body['server']['metadata'] = {1: 'test'}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_metadata_value_not_string(self):
        self.flags(quota_metadata_items=1)
        image_href = 'http://localhost/v2/images/%s' % self.image_uuid
        self.body['server']['image_ref'] = image_href
        self.body['server']['metadata'] = {'test': ['a', 'list']}
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_user_data_malformed_bad_request(self):
        params = {'os-user-data:user_data': 'u1234'}
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_invalid_key_name(self):
        image_href = 'http://localhost/v2/images/2'
        self.body['server']['image_ref'] = image_href
        self.body['server']['key_name'] = 'nonexistentkey'
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_valid_key_name(self):
        self.body['server']['key_name'] = 'key'
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        self.assertEqual(FAKE_UUID, res["server"]["id"])
        self._check_admin_password_len(res["server"])

    def test_create_instance_invalid_flavor_href(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = 'http://localhost/v2/flavors/asdf'
        self.body['server']['image_ref'] = image_href
        self.body['server']['flavor_ref'] = flavor_ref
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_invalid_flavor_id_int(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = -1
        self.body['server']['image_ref'] = image_href
        self.body['server']['flavor_ref'] = flavor_ref
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_bad_flavor_href(self):
        image_href = 'http://localhost/v2/images/2'
        flavor_ref = 'http://localhost/v2/flavors/17'
        self.body['server']['image_ref'] = image_href
        self.body['server']['flavor_ref'] = flavor_ref
        self.req.body = jsonutils.dumps(self.body)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_bad_href(self):
        image_href = 'asdf'
        self.body['server']['image_ref'] = image_href
        self.req.body = jsonutils.dumps(self.body)

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, self.req, body=self.body)

    def test_create_instance_local_href(self):
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self.assertEqual(FAKE_UUID, server['id'])

    def test_create_instance_admin_password(self):
        self.body['server']['flavor_ref'] = 3
        self.body['server']['admin_password'] = 'testpass'
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self.assertEqual(server['admin_password'],
                         self.body['server']['admin_password'])

    def test_create_instance_admin_password_pass_disabled(self):
        self.flags(enable_instance_password=False)
        self.body['server']['flavor_ref'] = 3
        self.body['server']['admin_password'] = 'testpass'
        self.req.body = jsonutils.dumps(self.body)
        res = self.controller.create(self.req, body=self.body).obj

        server = res['server']
        self.assertIn('admin_password', self.body['server'])

    def test_create_instance_admin_password_empty(self):
        self.body['server']['flavor_ref'] = 3
        self.body['server']['admin_password'] = ''
        self.req.body = jsonutils.dumps(self.body)

        # The fact that the action doesn't raise is enough validation
        self.controller.create(self.req, body=self.body)

    def test_create_location(self):
        selfhref = 'http://localhost/v2/fake/servers/%s' % FAKE_UUID
        self.req.body = jsonutils.dumps(self.body)
        robj = self.controller.create(self.req, body=self.body)

        self.assertEqual(robj['Location'], selfhref)

    def _do_test_create_instance_above_quota(self, resource, allowed, quota,
                                             expected_msg):
        fakes.stub_out_instance_quota(self.stubs, allowed, quota, resource)
        self.body['server']['flavor_ref'] = 3
        self.req.body = jsonutils.dumps(self.body)
        try:
            self.controller.create(self.req, body=self.body).obj['server']
            self.fail('expected quota to be exceeded')
        except webob.exc.HTTPRequestEntityTooLarge as e:
            self.assertEqual(e.explanation, expected_msg)

    def test_create_instance_above_quota_instances(self):
        msg = _('Quota exceeded for instances: Requested 1, but'
                ' already used 10 of 10 instances')
        self._do_test_create_instance_above_quota('instances', 0, 10, msg)

    def test_create_instance_above_quota_ram(self):
        msg = _('Quota exceeded for ram: Requested 4096, but'
                ' already used 8192 of 10240 ram')
        self._do_test_create_instance_above_quota('ram', 2048, 10 * 1024, msg)

    def test_create_instance_above_quota_cores(self):
        msg = _('Quota exceeded for cores: Requested 2, but'
                ' already used 9 of 10 cores')
        self._do_test_create_instance_above_quota('cores', 1, 10, msg)

    def test_create_instance_with_neutronv2_port_in_use(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.PortInUse(port_id=port)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPConflict,
                          self._test_create_extra, params)

    def test_create_multiple_instance_with_neutronv2_port(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        params = {'networks': requested_networks}
        self.body['server']['max_count'] = 2

        def fake_create(*args, **kwargs):
            msg = _("Unable to launch multiple instances with"
                    " a single configured port ID. Please launch your"
                    " instance one by one with different ports.")
            raise exception.MultiplePortsNotApplicable(reason=msg)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_neturonv2_not_found_network(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        requested_networks = [{'uuid': network}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.NetworkNotFound(network_id=network)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)

    def test_create_instance_with_neutronv2_port_not_found(self):
        network = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        port = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        requested_networks = [{'uuid': network, 'port': port}]
        params = {'networks': requested_networks}

        def fake_create(*args, **kwargs):
            raise exception.PortNotFound(port_id=port)

        self.stubs.Set(compute_api.API, 'create', fake_create)
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self._test_create_extra, params)


class ServersViewBuilderTest(test.TestCase):

    def setUp(self):
        super(ServersViewBuilderTest, self).setUp()
        CONF.set_override('glance_host', 'localhost')
        self.flags(use_ipv6=True)
        db_inst = fakes.stub_instance(
            id=1,
            image_ref="5",
            uuid="deadbeef-feed-edee-beef-d0ea7beefedd",
            display_name="test_server",
            include_fake_metadata=False)

        privates = ['172.19.0.1']
        publics = ['192.168.0.3']
        public6s = ['b33f::fdee:ddff:fecc:bbaa']

        def nw_info(*args, **kwargs):
            return [(None, {'label': 'public',
                            'ips': [dict(ip=ip) for ip in publics],
                            'ip6s': [dict(ip=ip) for ip in public6s]}),
                    (None, {'label': 'private',
                            'ips': [dict(ip=ip) for ip in privates]})]

        def floaters(*args, **kwargs):
            return []

        fakes.stub_out_nw_api_get_instance_nw_info(self.stubs, nw_info)
        fakes.stub_out_nw_api_get_floating_ips_by_fixed_address(self.stubs,
                                                                floaters)

        self.uuid = db_inst['uuid']
        self.view_builder = views.servers.ViewBuilderV3()
        self.request = fakes.HTTPRequestV3.blank("")
        self.request.context = context.RequestContext('fake', 'fake')
        self.instance = fake_instance.fake_instance_obj(
                    self.request.context,
                    expected_attrs=instance_obj.INSTANCE_DEFAULT_FIELDS,
                    **db_inst)

    def test_get_flavor_valid_instance_type(self):
        flavor_bookmark = "http://localhost/flavors/1"
        expected = {"id": "1",
                    "links": [{"rel": "bookmark",
                               "href": flavor_bookmark}]}
        result = self.view_builder._get_flavor(self.request, self.instance)
        self.assertEqual(result, expected)

    def test_build_server(self):
        self_link = "http://localhost/v3/servers/%s" % self.uuid
        bookmark_link = "http://localhost/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.basic(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_with_project_id(self):
        expected_server = {
            "server": {
                "id": self.uuid,
                "name": "test_server",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v3/servers/%s" %
                                self.uuid,
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/servers/%s" % self.uuid,
                    },
                ],
            }
        }

        output = self.view_builder.basic(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_detail(self):
        image_bookmark = "http://localhost:9292/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        self_link = "http://localhost/v3/servers/%s" % self.uuid
        bookmark_link = "http://localhost/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "host_id": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'}
                    ]
                },
                "metadata": {},
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_no_image(self):
        self.instance["image_ref"] = ""
        output = self.view_builder.show(self.request, self.instance)
        self.assertEqual(output['server']['image'], {})

    def test_build_server_detail_with_fault(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                     self.request.context, self.uuid)

        image_bookmark = "http://localhost:9292/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        self_link = "http://localhost/v3/servers/%s" % self.uuid
        bookmark_link = "http://localhost/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "name": "test_server",
                "status": "ERROR",
                "host_id": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'}
                    ]
                },
                "metadata": {},
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
                "fault": {
                    "code": 404,
                    "created": "2010-10-10T12:00:00Z",
                    "message": "HTTPNotFound",
                    "details": "Stock details for test",
                },
            }
        }

        self.request.context = context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_detail_with_fault_that_has_been_deleted(self):
        self.instance['deleted'] = 1
        self.instance['vm_state'] = vm_states.ERROR
        fault = fake_instance.fake_fault_obj(self.request.context,
                                             self.uuid, code=500,
                                             message="No valid host was found")
        self.instance['fault'] = fault

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "No valid host was found"}

        self.request.context = context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        # Regardless of vm_state deleted servers sholud be DELETED
        self.assertEqual("DELETED", output['server']['status'])
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_no_details_not_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.context = context.RequestContext('fake', 'fake')
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error",
                          'details': 'Stock details for test'}

        self.request.environ['nova.context'].is_admin = True
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_no_details_admin(self):
        self.instance['vm_state'] = vm_states.ERROR
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                                   self.request.context,
                                                   self.uuid,
                                                   code=500,
                                                   message='Error',
                                                   details='')

        expected_fault = {"code": 500,
                          "created": "2010-10-10T12:00:00Z",
                          "message": "Error"}

        self.request.environ['nova.context'].is_admin = True
        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output['server']['fault'],
                        matchers.DictMatches(expected_fault))

    def test_build_server_detail_with_fault_but_active(self):
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100
        self.instance['fault'] = fake_instance.fake_fault_obj(
                                     self.request.context, self.uuid)

        output = self.view_builder.show(self.request, self.instance)
        self.assertNotIn('fault', output['server'])

    def test_build_server_detail_active_status(self):
        #set the power state of the instance to running
        self.instance['vm_state'] = vm_states.ACTIVE
        self.instance['progress'] = 100
        image_bookmark = "http://localhost:9292/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        self_link = "http://localhost/v3/servers/%s" % self.uuid
        bookmark_link = "http://localhost/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 100,
                "name": "test_server",
                "status": "ACTIVE",
                "host_id": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                  "links": [
                                            {
                          "rel": "bookmark",
                          "href": flavor_bookmark,
                      },
                  ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'}
                    ]
                },
                "metadata": {},
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))

    def test_build_server_detail_with_metadata(self):

        metadata = []
        metadata.append(models.InstanceMetadata(key="Open", value="Stack"))
        metadata = nova_utils.metadata_to_dict(metadata)
        self.instance['metadata'] = metadata

        image_bookmark = "http://localhost:9292/images/5"
        flavor_bookmark = "http://localhost/flavors/1"
        self_link = "http://localhost/v3/servers/%s" % self.uuid
        bookmark_link = "http://localhost/servers/%s" % self.uuid
        expected_server = {
            "server": {
                "id": self.uuid,
                "user_id": "fake_user",
                "tenant_id": "fake_project",
                "updated": "2010-11-11T11:00:00Z",
                "created": "2010-10-10T12:00:00Z",
                "progress": 0,
                "name": "test_server",
                "status": "BUILD",
                "host_id": '',
                "image": {
                    "id": "5",
                    "links": [
                        {
                            "rel": "bookmark",
                            "href": image_bookmark,
                        },
                    ],
                },
                "flavor": {
                    "id": "1",
                    "links": [
                                              {
                            "rel": "bookmark",
                            "href": flavor_bookmark,
                        },
                    ],
                },
                "addresses": {
                    'test1': [
                        {'version': 4, 'addr': '192.168.1.100',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                        {'version': 6, 'addr': '2001:db8:0:1::1',
                         'type': 'fixed', 'mac_addr': 'aa:aa:aa:aa:aa:aa'},
                    ]
                },
                "metadata": {"Open": "Stack"},
                "links": [
                    {
                        "rel": "self",
                        "href": self_link,
                    },
                    {
                        "rel": "bookmark",
                        "href": bookmark_link,
                    },
                ],
            }
        }

        output = self.view_builder.show(self.request, self.instance)
        self.assertThat(output, matchers.DictMatches(expected_server))


class ServersAllExtensionsTestCase(test.TestCase):
    """Servers tests using default API router with all extensions enabled.

    The intent here is to catch cases where extensions end up throwing
    an exception because of a malformed request before the core API
    gets a chance to validate the request and return a 422 response.

    For example, AccessIPsController extends servers.Controller:

        @wsgi.extends
        def create(self, req, resp_obj, body):
            context = req.environ['nova.context']
            if authorize(context) and 'server' in resp_obj.obj:
                resp_obj.attach(xml=AccessIPTemplate())
                server = resp_obj.obj['server']
                self._extend_server(req, server)

    we want to ensure that the extension isn't barfing on an invalid
    body.
    """

    def setUp(self):
        super(ServersAllExtensionsTestCase, self).setUp()
        self.app = compute.APIRouterV3()

    def test_create_missing_server(self):
        # Test create with malformed body.

        def fake_create(*args, **kwargs):
            raise test.TestingException("Should not reach the compute API.")

        self.stubs.Set(compute_api.API, 'create', fake_create)

        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'
        req.content_type = 'application/json'
        body = {'foo': {'a': 'b'}}

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)

    def test_update_missing_server(self):
        # Test create with malformed body.

        def fake_update(*args, **kwargs):
            raise test.TestingException("Should not reach the compute API.")

        self.stubs.Set(compute_api.API, 'create', fake_update)

        req = fakes.HTTPRequestV3.blank('/servers/1')
        req.method = 'PUT'
        req.content_type = 'application/json'
        body = {'foo': {'a': 'b'}}

        req.body = jsonutils.dumps(body)
        res = req.get_response(self.app)
        self.assertEqual(400, res.status_int)


class ServersInvalidRequestTestCase(test.TestCase):
    """Tests of places we throw 400 Bad Request from."""

    def setUp(self):
        super(ServersInvalidRequestTestCase, self).setUp()
        ext_info = plugins.LoadedExtensionInfo()
        self.controller = servers.ServersController(extension_info=ext_info)

    def _invalid_server_create(self, body):
        req = fakes.HTTPRequestV3.blank('/servers')
        req.method = 'POST'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.create, req, body=body)

    def test_create_server_no_body(self):
        self._invalid_server_create(body=None)

    def test_create_server_missing_server(self):
        body = {'foo': {'a': 'b'}}
        self._invalid_server_create(body=body)

    def test_create_server_malformed_entity(self):
        body = {'server': 'string'}
        self._invalid_server_create(body=body)

    def _unprocessable_server_update(self, body):
        req = fakes.HTTPRequestV3.blank('/servers/%s' % FAKE_UUID)
        req.method = 'PUT'

        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.update, req, FAKE_UUID, body=body)

    def test_update_server_no_body(self):
        self._invalid_server_create(body=None)

    def test_update_server_missing_server(self):
        body = {'foo': {'a': 'b'}}
        self._invalid_server_create(body=body)

    def test_create_update_malformed_entity(self):
        body = {'server': 'string'}
        self._invalid_server_create(body=body)


class FakeExt(extensions.V3APIExtensionBase):
    name = "AccessIPs"
    alias = 'os-access-ips'
    version = 1

    def fake_extension_point(self, *args, **kwargs):
        pass

    def get_controller_extensions(self):
        return []

    def get_resources(self):
        return []


class TestServersExtensionPoint(test.NoDBTestCase):
    def setUp(self):
        super(TestServersExtensionPoint, self).setUp()
        CONF.set_override('extensions_whitelist', ['os-access-ips'],
                          'osapi_v3')
        self.stubs.Set(access_ips, 'AccessIPs', FakeExt)

    def _test_load_extension_point(self, name):
        setattr(FakeExt, 'server_%s' % name,
                FakeExt.fake_extension_point)
        ext_info = plugins.LoadedExtensionInfo()
        controller = servers.ServersController(extension_info=ext_info)
        self.assertEqual(
            'os-access-ips',
            list(getattr(controller,
                         '%s_extension_manager' % name))[0].obj.alias)
        delattr(FakeExt, 'server_%s' % name)

    def test_load_update_extension_point(self):
        self._test_load_extension_point('update')

    def test_load_rebuild_extension_point(self):
        self._test_load_extension_point('rebuild')

    def test_load_create_extension_point(self):
        self._test_load_extension_point('create')
