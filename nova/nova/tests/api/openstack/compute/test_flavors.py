# Copyright 2012 OpenStack Foundation
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

from lxml import etree
import six.moves.urllib.parse as urlparse
import webob

from nova.api.openstack.compute import flavors
from nova.api.openstack import xmlutil
import nova.compute.flavors
from nova import context
from nova import db
from nova import exception
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import matchers

NS = "{http://docs.openstack.org/compute/api/v1.1}"
ATOMNS = "{http://www.w3.org/2005/Atom}"


FAKE_FLAVORS = {
    'flavor 1': {
        "flavorid": '1',
        "name": 'flavor 1',
        "memory_mb": '256',
        "root_gb": '10',
    },
    'flavor 2': {
        "flavorid": '2',
        "name": 'flavor 2',
        "memory_mb": '512',
        "root_gb": '20',
    },
}


def fake_flavor_get_by_flavor_id(flavorid, ctxt=None):
    return FAKE_FLAVORS['flavor %s' % flavorid]


def fake_get_all_flavors_sorted_list(context=None, inactive=False,
                                     filters=None, sort_key='flavorid',
                                     sort_dir='asc', limit=None, marker=None):
    if marker in ['99999']:
        raise exception.MarkerNotFound(marker)

    def reject_min(db_attr, filter_attr):
        return (filter_attr in filters and
                int(flavor[db_attr]) < int(filters[filter_attr]))

    filters = filters or {}
    res = []
    for (flavor_name, flavor) in FAKE_FLAVORS.items():
        if reject_min('memory_mb', 'min_memory_mb'):
            continue
        elif reject_min('root_gb', 'min_root_gb'):
            continue

        res.append(flavor)

    res = sorted(res, key=lambda item: item[sort_key])
    output = []
    marker_found = True if marker is None else False
    for flavor in res:
        if not marker_found and marker == flavor['flavorid']:
            marker_found = True
        elif marker_found:
            if limit is None or len(output) < int(limit):
                output.append(flavor)

    return output


def empty_get_all_flavors_sorted_list(context=None, inactive=False,
                                      filters=None, sort_key='flavorid',
                                      sort_dir='asc', limit=None, marker=None):
    return []


def return_flavor_not_found(flavor_id, ctxt=None):
    raise exception.FlavorNotFound(flavor_id=flavor_id)


class FlavorsTest(test.TestCase):
    def setUp(self):
        super(FlavorsTest, self).setUp()
        self.flags(osapi_compute_extension=[])
        fakes.stub_out_networking(self.stubs)
        fakes.stub_out_rate_limiting(self.stubs)
        self.stubs.Set(nova.compute.flavors, "get_all_flavors_sorted_list",
                       fake_get_all_flavors_sorted_list)
        self.stubs.Set(nova.compute.flavors,
                       "get_flavor_by_flavor_id",
                       fake_flavor_get_by_flavor_id)

        self.controller = flavors.Controller()

    def test_get_flavor_by_invalid_id(self):
        self.stubs.Set(nova.compute.flavors,
                       "get_flavor_by_flavor_id",
                       return_flavor_not_found)
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/asdf')
        self.assertRaises(webob.exc.HTTPNotFound,
                          self.controller.show, req, 'asdf')

    def test_get_flavor_by_id(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1')
        flavor = self.controller.show(req, '1')
        expected = {
            "flavor": {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/1",
                    },
                ],
            },
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_with_custom_link_prefix(self):
        self.flags(osapi_compute_link_prefix='http://zoo.com:42',
                   osapi_glance_link_prefix='http://circus.com:34')
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/1')
        flavor = self.controller.show(req, '1')
        expected = {
            "flavor": {
                "id": "1",
                "name": "flavor 1",
                "ram": "256",
                "disk": "10",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://zoo.com:42/v2/fake/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://zoo.com:42/fake/flavors/1",
                    },
                ],
            },
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_list(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/1",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/1",
                        },
                    ],
                },
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_with_marker(self):
        self.maxDiff = None
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?limit=1&marker=1')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
            'flavors_links': [
                {'href': 'http://localhost/v2/fake/flavors?limit=1&marker=2',
               'rel': 'next'}
            ]
        }
        self.assertThat(flavor, matchers.DictMatches(expected))

    def test_get_flavor_list_with_invalid_marker(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?marker=99999')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_detail_with_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/detail?limit=1')
        response = self.controller.index(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        alternate = "%s/fake/flavors/%s"

        expected_flavors = [
            {
                "id": "1",
                "name": "flavor 1",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/1",
                    },
                ],
            },
        ]
        self.assertEqual(response_list, expected_flavors)
        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/flavors', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['1'], 'marker': ['1']},
                        matchers.DictMatches(params))

    def test_get_flavor_with_limit(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?limit=2')
        response = self.controller.index(req)
        response_list = response["flavors"]
        response_links = response["flavors_links"]

        alternate = "%s/fake/flavors/%s"

        expected_flavors = [
            {
                "id": "1",
                "name": "flavor 1",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/1",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/1",
                    },
                ],
            },
            {
                "id": "2",
                "name": "flavor 2",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/2",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/2",
                    },
                ],
            }
        ]
        self.assertEqual(response_list, expected_flavors)
        self.assertEqual(response_links[0]['rel'], 'next')

        href_parts = urlparse.urlparse(response_links[0]['href'])
        self.assertEqual('/v2/fake/flavors', href_parts.path)
        params = urlparse.parse_qs(href_parts.query)
        self.assertThat({'limit': ['2'], 'marker': ['2']},
                        matchers.DictMatches(params))

    def test_get_flavor_list_detail(self):
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/detail')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "1",
                    "name": "flavor 1",
                    "ram": "256",
                    "disk": "10",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/1",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/1",
                        },
                    ],
                },
                {
                    "id": "2",
                    "name": "flavor 2",
                    "ram": "512",
                    "disk": "20",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
        }
        self.assertEqual(flavor, expected)

    def test_get_empty_flavor_list(self):
        self.stubs.Set(nova.compute.flavors, "get_all_flavors_sorted_list",
                       empty_get_all_flavors_sorted_list)

        req = fakes.HTTPRequest.blank('/v2/fake/flavors')
        flavors = self.controller.index(req)
        expected = {'flavors': []}
        self.assertEqual(flavors, expected)

    def test_get_flavor_list_filter_min_ram(self):
        # Flavor lists may be filtered by minRam.
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?minRam=512')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_filter_invalid_min_ram(self):
        # Ensure you cannot list flavors with invalid minRam param.
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?minRam=NaN')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_list_filter_min_disk(self):
        # Flavor lists may be filtered by minDisk.
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?minDisk=20')
        flavor = self.controller.index(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
        }
        self.assertEqual(flavor, expected)

    def test_get_flavor_list_filter_invalid_min_disk(self):
        # Ensure you cannot list flavors with invalid minDisk param.
        req = fakes.HTTPRequest.blank('/v2/fake/flavors?minDisk=NaN')
        self.assertRaises(webob.exc.HTTPBadRequest,
                          self.controller.index, req)

    def test_get_flavor_list_detail_min_ram_and_min_disk(self):
        """Tests that filtering work on flavor details and that minRam and
        minDisk filters can be combined
        """
        req = fakes.HTTPRequest.blank('/v2/fake/flavors/detail'
                                      '?minRam=256&minDisk=20')
        flavor = self.controller.detail(req)
        expected = {
            "flavors": [
                {
                    "id": "2",
                    "name": "flavor 2",
                    "ram": "512",
                    "disk": "20",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/2",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/2",
                        },
                    ],
                },
            ],
        }
        self.assertEqual(flavor, expected)


class FlavorsXMLSerializationTest(test.TestCase):

    def test_xml_declaration(self):
        serializer = flavors.FlavorTemplate()

        fixture = {
            "flavor": {
                "id": "12",
                "name": "asdf",
                "ram": "256",
                "disk": "10",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        has_dec = output.startswith("<?xml version='1.0' encoding='UTF-8'?>")
        self.assertTrue(has_dec)

    def test_show(self):
        serializer = flavors.FlavorTemplate()

        fixture = {
            "flavor": {
                "id": "12",
                "name": "asdf",
                "ram": "256",
                "disk": "10",
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavor')
        flavor_dict = fixture['flavor']

        for key in ['name', 'id', 'ram', 'disk']:
            self.assertEqual(root.get(key), str(flavor_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(flavor_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_show_handles_integers(self):
        serializer = flavors.FlavorTemplate()

        fixture = {
            "flavor": {
                "id": 12,
                "name": "asdf",
                "ram": 256,
                "disk": 10,
                "vcpus": "",
                "links": [
                    {
                        "rel": "self",
                        "href": "http://localhost/v2/fake/flavors/12",
                    },
                    {
                        "rel": "bookmark",
                        "href": "http://localhost/fake/flavors/12",
                    },
                ],
            },
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavor')
        flavor_dict = fixture['flavor']

        for key in ['name', 'id', 'ram', 'disk']:
            self.assertEqual(root.get(key), str(flavor_dict[key]))

        link_nodes = root.findall('{0}link'.format(ATOMNS))
        self.assertEqual(len(link_nodes), 2)
        for i, link in enumerate(flavor_dict['links']):
            for key, value in link.items():
                self.assertEqual(link_nodes[i].get(key), value)

    def test_detail(self):
        serializer = flavors.FlavorsTemplate()

        fixture = {
            "flavors": [
                {
                    "id": "23",
                    "name": "flavor 23",
                    "ram": "512",
                    "disk": "20",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/23",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/23",
                        },
                    ],
                },
                {
                    "id": "13",
                    "name": "flavor 13",
                    "ram": "256",
                    "disk": "10",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/13",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/13",
                        },
                    ],
                },
            ],
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavors')
        flavor_elems = root.findall('{0}flavor'.format(NS))
        self.assertEqual(len(flavor_elems), 2)
        for i, flavor_elem in enumerate(flavor_elems):
            flavor_dict = fixture['flavors'][i]

            for key in ['name', 'id', 'ram', 'disk']:
                self.assertEqual(flavor_elem.get(key), str(flavor_dict[key]))

            link_nodes = flavor_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(flavor_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

    def test_index(self):
        serializer = flavors.MinimalFlavorsTemplate()

        fixture = {
            "flavors": [
                {
                    "id": "23",
                    "name": "flavor 23",
                    "ram": "512",
                    "disk": "20",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/23",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/23",
                        },
                    ],
                },
                {
                    "id": "13",
                    "name": "flavor 13",
                    "ram": "256",
                    "disk": "10",
                    "vcpus": "",
                    "links": [
                        {
                            "rel": "self",
                            "href": "http://localhost/v2/fake/flavors/13",
                        },
                        {
                            "rel": "bookmark",
                            "href": "http://localhost/fake/flavors/13",
                        },
                    ],
                },
            ],
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavors_index')
        flavor_elems = root.findall('{0}flavor'.format(NS))
        self.assertEqual(len(flavor_elems), 2)
        for i, flavor_elem in enumerate(flavor_elems):
            flavor_dict = fixture['flavors'][i]

            for key in ['name', 'id']:
                self.assertEqual(flavor_elem.get(key), str(flavor_dict[key]))

            link_nodes = flavor_elem.findall('{0}link'.format(ATOMNS))
            self.assertEqual(len(link_nodes), 2)
            for i, link in enumerate(flavor_dict['links']):
                for key, value in link.items():
                    self.assertEqual(link_nodes[i].get(key), value)

    def test_index_empty(self):
        serializer = flavors.MinimalFlavorsTemplate()

        fixture = {
            "flavors": [],
        }

        output = serializer.serialize(fixture)
        root = etree.XML(output)
        xmlutil.validate_schema(root, 'flavors_index')
        flavor_elems = root.findall('{0}flavor'.format(NS))
        self.assertEqual(len(flavor_elems), 0)


class DisabledFlavorsWithRealDBTest(test.TestCase):
    """Tests that disabled flavors should not be shown nor listed."""
    def setUp(self):
        super(DisabledFlavorsWithRealDBTest, self).setUp()
        self.controller = flavors.Controller()

        # Add a new disabled type to the list of flavors
        self.req = fakes.HTTPRequest.blank('/v2/fake/flavors')
        self.context = self.req.environ['nova.context']
        self.admin_context = context.get_admin_context()

        self.disabled_type = self._create_disabled_instance_type()
        self.inst_types = db.flavor_get_all(
                self.admin_context)

    def tearDown(self):
        db.flavor_destroy(
                self.admin_context, self.disabled_type['name'])

        super(DisabledFlavorsWithRealDBTest, self).tearDown()

    def _create_disabled_instance_type(self):
        inst_types = db.flavor_get_all(self.admin_context)

        inst_type = inst_types[0]

        del inst_type['id']
        inst_type['name'] += '.disabled'
        inst_type['flavorid'] = unicode(max(
                [int(flavor['flavorid']) for flavor in inst_types]) + 1)
        inst_type['disabled'] = True

        disabled_type = db.flavor_create(
                self.admin_context, inst_type)

        return disabled_type

    def test_index_should_not_list_disabled_flavors_to_user(self):
        self.context.is_admin = False

        flavor_list = self.controller.index(self.req)['flavors']
        api_flavorids = set(f['id'] for f in flavor_list)

        db_flavorids = set(i['flavorid'] for i in self.inst_types)
        disabled_flavorid = str(self.disabled_type['flavorid'])

        self.assertIn(disabled_flavorid, db_flavorids)
        self.assertEqual(db_flavorids - set([disabled_flavorid]),
                         api_flavorids)

    def test_index_should_list_disabled_flavors_to_admin(self):
        self.context.is_admin = True

        flavor_list = self.controller.index(self.req)['flavors']
        api_flavorids = set(f['id'] for f in flavor_list)

        db_flavorids = set(i['flavorid'] for i in self.inst_types)
        disabled_flavorid = str(self.disabled_type['flavorid'])

        self.assertIn(disabled_flavorid, db_flavorids)
        self.assertEqual(db_flavorids, api_flavorids)

    def test_show_should_include_disabled_flavor_for_user(self):
        """Counterintuitively we should show disabled flavors to all users and
        not just admins. The reason is that, when a user performs a server-show
        request, we want to be able to display the pretty flavor name ('512 MB
        Instance') and not just the flavor-id even if the flavor id has been
        marked disabled.
        """
        self.context.is_admin = False

        flavor = self.controller.show(
                self.req, self.disabled_type['flavorid'])['flavor']

        self.assertEqual(flavor['name'], self.disabled_type['name'])

    def test_show_should_include_disabled_flavor_for_admin(self):
        self.context.is_admin = True

        flavor = self.controller.show(
                self.req, self.disabled_type['flavorid'])['flavor']

        self.assertEqual(flavor['name'], self.disabled_type['name'])


class ParseIsPublicTest(test.TestCase):
    def setUp(self):
        super(ParseIsPublicTest, self).setUp()
        self.controller = flavors.Controller()

    def assertPublic(self, expected, is_public):
        self.assertIs(expected, self.controller._parse_is_public(is_public),
                      '%s did not return %s' % (is_public, expected))

    def test_None(self):
        self.assertPublic(True, None)

    def test_truthy(self):
        self.assertPublic(True, True)
        self.assertPublic(True, 't')
        self.assertPublic(True, 'true')
        self.assertPublic(True, 'yes')
        self.assertPublic(True, '1')

    def test_falsey(self):
        self.assertPublic(False, False)
        self.assertPublic(False, 'f')
        self.assertPublic(False, 'false')
        self.assertPublic(False, 'no')
        self.assertPublic(False, '0')

    def test_string_none(self):
        self.assertPublic(None, 'none')
        self.assertPublic(None, 'None')

    def test_other(self):
        self.assertRaises(
                webob.exc.HTTPBadRequest, self.assertPublic, None, 'other')
