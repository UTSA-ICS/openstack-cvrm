# Copyright 2011-2012 OpenStack Foundation
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

import copy

from lxml import etree
from webob import exc

from nova.api.openstack.compute.contrib import cells as cells_ext
from nova.api.openstack import extensions
from nova.api.openstack import xmlutil
from nova.cells import rpcapi as cells_rpcapi
from nova import context
from nova import exception
from nova.openstack.common import timeutils
from nova import rpc
from nova import test
from nova.tests.api.openstack import fakes
from nova.tests import utils


class BaseCellsTest(test.NoDBTestCase):
    def setUp(self):
        super(BaseCellsTest, self).setUp()

        self.fake_cells = [
                dict(id=1, name='cell1', is_parent=True,
                     weight_scale=1.0, weight_offset=0.0,
                     transport_url='rabbit://bob:xxxx@r1.example.org/'),
                dict(id=2, name='cell2', is_parent=False,
                     weight_scale=1.0, weight_offset=0.0,
                     transport_url='rabbit://alice:qwerty@r2.example.org/')]

        self.fake_capabilities = [
                {'cap1': '0,1', 'cap2': '2,3'},
                {'cap3': '4,5', 'cap4': '5,6'}]

        def fake_cell_get(_self, context, cell_name):
            for cell in self.fake_cells:
                if cell_name == cell['name']:
                    return cell
            else:
                raise exception.CellNotFound(cell_name=cell_name)

        def fake_cell_create(_self, context, values):
            cell = dict(id=1)
            cell.update(values)
            return cell

        def fake_cell_update(_self, context, cell_id, values):
            cell = fake_cell_get(_self, context, cell_id)
            cell.update(values)
            return cell

        def fake_cells_api_get_all_cell_info(*args):
            return self._get_all_cell_info(*args)

        self.stubs.Set(cells_rpcapi.CellsAPI, 'cell_get', fake_cell_get)
        self.stubs.Set(cells_rpcapi.CellsAPI, 'cell_update', fake_cell_update)
        self.stubs.Set(cells_rpcapi.CellsAPI, 'cell_create', fake_cell_create)
        self.stubs.Set(cells_rpcapi.CellsAPI, 'get_cell_info_for_neighbors',
                fake_cells_api_get_all_cell_info)

    def _get_all_cell_info(self, *args):
        def insecure_transport_url(url):
            transport_url = rpc.get_transport_url(url)
            transport_url.hosts[0].password = None
            return str(transport_url)

        cells = copy.deepcopy(self.fake_cells)
        cells[0]['transport_url'] = insecure_transport_url(
                cells[0]['transport_url'])
        cells[1]['transport_url'] = insecure_transport_url(
                cells[1]['transport_url'])
        for i, cell in enumerate(cells):
                cell['capabilities'] = self.fake_capabilities[i]
        return cells


class CellsTest(BaseCellsTest):
    def setUp(self):
        super(CellsTest, self).setUp()
        self.ext_mgr = self.mox.CreateMock(extensions.ExtensionManager)
        self.controller = cells_ext.Controller(self.ext_mgr)
        self.context = context.get_admin_context()
        self.flags(enable=True, group='cells')

    def _get_request(self, resource):
        return fakes.HTTPRequest.blank('/v2/fake/' + resource)

    def test_index(self):
        req = self._get_request("cells")
        res_dict = self.controller.index(req)

        self.assertEqual(len(res_dict['cells']), 2)
        for i, cell in enumerate(res_dict['cells']):
            self.assertEqual(cell['name'], self.fake_cells[i]['name'])
            self.assertNotIn('capabilitiles', cell)
            self.assertNotIn('password', cell)

    def test_detail(self):
        req = self._get_request("cells/detail")
        res_dict = self.controller.detail(req)

        self.assertEqual(len(res_dict['cells']), 2)
        for i, cell in enumerate(res_dict['cells']):
            self.assertEqual(cell['name'], self.fake_cells[i]['name'])
            self.assertEqual(cell['capabilities'], self.fake_capabilities[i])
            self.assertNotIn('password', cell)

    def test_show_bogus_cell_raises(self):
        req = self._get_request("cells/bogus")
        self.assertRaises(exc.HTTPNotFound, self.controller.show, req, 'bogus')

    def test_get_cell_by_name(self):
        req = self._get_request("cells/cell1")
        res_dict = self.controller.show(req, 'cell1')
        cell = res_dict['cell']

        self.assertEqual(cell['name'], 'cell1')
        self.assertEqual(cell['rpc_host'], 'r1.example.org')
        self.assertNotIn('password', cell)

    def test_cell_delete(self):
        call_info = {'delete_called': 0}

        def fake_cell_delete(inst, context, cell_name):
            self.assertEqual(cell_name, 'cell999')
            call_info['delete_called'] += 1

        self.stubs.Set(cells_rpcapi.CellsAPI, 'cell_delete', fake_cell_delete)

        req = self._get_request("cells/cell999")
        self.controller.delete(req, 'cell999')
        self.assertEqual(call_info['delete_called'], 1)

    def test_delete_bogus_cell_raises(self):
        def fake_cell_delete(inst, context, cell_name):
            return 0

        self.stubs.Set(cells_rpcapi.CellsAPI, 'cell_delete', fake_cell_delete)

        req = self._get_request("cells/cell999")
        req.environ['nova.context'] = self.context
        self.assertRaises(exc.HTTPNotFound, self.controller.delete, req,
                'cell999')

    def test_cell_create_parent(self):
        body = {'cell': {'name': 'meow',
                        'username': 'fred',
                        'password': 'fubar',
                        'rpc_host': 'r3.example.org',
                        'type': 'parent',
                        # Also test this is ignored/stripped
                        'is_parent': False}}

        req = self._get_request("cells")
        res_dict = self.controller.create(req, body)
        cell = res_dict['cell']

        self.assertEqual(cell['name'], 'meow')
        self.assertEqual(cell['username'], 'fred')
        self.assertEqual(cell['rpc_host'], 'r3.example.org')
        self.assertEqual(cell['type'], 'parent')
        self.assertNotIn('password', cell)
        self.assertNotIn('is_parent', cell)

    def test_cell_create_child(self):
        body = {'cell': {'name': 'meow',
                        'username': 'fred',
                        'password': 'fubar',
                        'rpc_host': 'r3.example.org',
                        'type': 'child'}}

        req = self._get_request("cells")
        res_dict = self.controller.create(req, body)
        cell = res_dict['cell']

        self.assertEqual(cell['name'], 'meow')
        self.assertEqual(cell['username'], 'fred')
        self.assertEqual(cell['rpc_host'], 'r3.example.org')
        self.assertEqual(cell['type'], 'child')
        self.assertNotIn('password', cell)
        self.assertNotIn('is_parent', cell)

    def test_cell_create_no_name_raises(self):
        body = {'cell': {'username': 'moocow',
                         'password': 'secret',
                         'rpc_host': 'r3.example.org',
                         'type': 'parent'}}

        req = self._get_request("cells")
        self.assertRaises(exc.HTTPBadRequest,
            self.controller.create, req, body)

    def test_cell_create_name_empty_string_raises(self):
        body = {'cell': {'name': '',
                         'username': 'fred',
                         'password': 'secret',
                         'rpc_host': 'r3.example.org',
                         'type': 'parent'}}

        req = self._get_request("cells")
        self.assertRaises(exc.HTTPBadRequest,
            self.controller.create, req, body)

    def test_cell_create_name_with_bang_raises(self):
        body = {'cell': {'name': 'moo!cow',
                         'username': 'fred',
                         'password': 'secret',
                         'rpc_host': 'r3.example.org',
                         'type': 'parent'}}

        req = self._get_request("cells")
        self.assertRaises(exc.HTTPBadRequest,
            self.controller.create, req, body)

    def test_cell_create_name_with_dot_raises(self):
        body = {'cell': {'name': 'moo.cow',
                         'username': 'fred',
                         'password': 'secret',
                         'rpc_host': 'r3.example.org',
                         'type': 'parent'}}

        req = self._get_request("cells")
        self.assertRaises(exc.HTTPBadRequest,
            self.controller.create, req, body)

    def test_cell_create_name_with_invalid_type_raises(self):
        body = {'cell': {'name': 'moocow',
                         'username': 'fred',
                         'password': 'secret',
                         'rpc_host': 'r3.example.org',
                         'type': 'invalid'}}

        req = self._get_request("cells")
        self.assertRaises(exc.HTTPBadRequest,
            self.controller.create, req, body)

    def test_cell_update(self):
        body = {'cell': {'username': 'zeb',
                         'password': 'sneaky'}}

        req = self._get_request("cells/cell1")
        res_dict = self.controller.update(req, 'cell1', body)
        cell = res_dict['cell']

        self.assertEqual(cell['name'], 'cell1')
        self.assertEqual(cell['rpc_host'], 'r1.example.org')
        self.assertEqual(cell['username'], 'zeb')
        self.assertNotIn('password', cell)

    def test_cell_update_empty_name_raises(self):
        body = {'cell': {'name': '',
                         'username': 'zeb',
                         'password': 'sneaky'}}

        req = self._get_request("cells/cell1")
        self.assertRaises(exc.HTTPBadRequest,
            self.controller.update, req, 'cell1', body)

    def test_cell_update_invalid_type_raises(self):
        body = {'cell': {'username': 'zeb',
                         'type': 'invalid',
                         'password': 'sneaky'}}

        req = self._get_request("cells/cell1")
        self.assertRaises(exc.HTTPBadRequest,
            self.controller.update, req, 'cell1', body)

    def test_cell_update_without_type_specified(self):
        body = {'cell': {'username': 'wingwj'}}

        req = self._get_request("cells/cell1")
        res_dict = self.controller.update(req, 'cell1', body)
        cell = res_dict['cell']

        self.assertEqual(cell['name'], 'cell1')
        self.assertEqual(cell['rpc_host'], 'r1.example.org')
        self.assertEqual(cell['username'], 'wingwj')
        self.assertEqual(cell['type'], 'parent')

    def test_cell_update_with_type_specified(self):
        body1 = {'cell': {'username': 'wingwj', 'type': 'child'}}
        body2 = {'cell': {'username': 'wingwj', 'type': 'parent'}}

        req1 = self._get_request("cells/cell1")
        res_dict1 = self.controller.update(req1, 'cell1', body1)
        cell1 = res_dict1['cell']

        req2 = self._get_request("cells/cell2")
        res_dict2 = self.controller.update(req2, 'cell2', body2)
        cell2 = res_dict2['cell']

        self.assertEqual(cell1['name'], 'cell1')
        self.assertEqual(cell1['rpc_host'], 'r1.example.org')
        self.assertEqual(cell1['username'], 'wingwj')
        self.assertEqual(cell1['type'], 'child')

        self.assertEqual(cell2['name'], 'cell2')
        self.assertEqual(cell2['rpc_host'], 'r2.example.org')
        self.assertEqual(cell2['username'], 'wingwj')
        self.assertEqual(cell2['type'], 'parent')

    def test_cell_info(self):
        caps = ['cap1=a;b', 'cap2=c;d']
        self.flags(name='darksecret', capabilities=caps, group='cells')

        req = self._get_request("cells/info")
        res_dict = self.controller.info(req)
        cell = res_dict['cell']
        cell_caps = cell['capabilities']

        self.assertEqual(cell['name'], 'darksecret')
        self.assertEqual(cell_caps['cap1'], 'a;b')
        self.assertEqual(cell_caps['cap2'], 'c;d')

    def test_show_capacities(self):
        self.ext_mgr.is_loaded('os-cell-capacities').AndReturn(True)
        self.mox.StubOutWithMock(self.controller.cells_rpcapi,
                                 'get_capacities')
        response = {"ram_free":
                        {"units_by_mb": {"8192": 0, "512": 13,
                                "4096": 1, "2048": 3, "16384": 0},
                        "total_mb": 7680},
                    "disk_free":
                        {"units_by_mb": {"81920": 11, "20480": 46,
                                "40960": 23, "163840": 5, "0": 0},
                        "total_mb": 1052672}
                    }
        self.controller.cells_rpcapi.\
            get_capacities(self.context, cell_name=None).AndReturn(response)
        self.mox.ReplayAll()
        req = self._get_request("cells/capacities")
        req.environ["nova.context"] = self.context
        res_dict = self.controller.capacities(req)
        self.assertEqual(response, res_dict['cell']['capacities'])

    def test_show_capacity_fails_with_non_admin_context(self):
        self.ext_mgr.is_loaded('os-cell-capacities').AndReturn(True)
        rules = {"compute_extension:cells": "is_admin:true"}
        self.policy.set_rules(rules)

        self.mox.ReplayAll()
        req = self._get_request("cells/capacities")
        req.environ["nova.context"] = self.context
        req.environ["nova.context"].is_admin = False
        self.assertRaises(exception.PolicyNotAuthorized,
                          self.controller.capacities, req)

    def test_show_capacities_for_invalid_cell(self):
        self.ext_mgr.is_loaded('os-cell-capacities').AndReturn(True)
        self.mox.StubOutWithMock(self.controller.cells_rpcapi,
                                 'get_capacities')
        self.controller.cells_rpcapi. \
            get_capacities(self.context, cell_name="invalid_cell").AndRaise(
            exception.CellNotFound(cell_name="invalid_cell"))
        self.mox.ReplayAll()
        req = self._get_request("cells/invalid_cell/capacities")
        req.environ["nova.context"] = self.context
        self.assertRaises(exc.HTTPNotFound,
                          self.controller.capacities, req, "invalid_cell")

    def test_show_capacities_for_cell(self):
        self.ext_mgr.is_loaded('os-cell-capacities').AndReturn(True)
        self.mox.StubOutWithMock(self.controller.cells_rpcapi,
                                 'get_capacities')
        response = {"ram_free":
                        {"units_by_mb": {"8192": 0, "512": 13,
                                "4096": 1, "2048": 3, "16384": 0},
                        "total_mb": 7680},
                    "disk_free":
                        {"units_by_mb": {"81920": 11, "20480": 46,
                                "40960": 23, "163840": 5, "0": 0},
                        "total_mb": 1052672}
                    }
        self.controller.cells_rpcapi.\
                        get_capacities(self.context, cell_name='cell_name').\
                            AndReturn(response)
        self.mox.ReplayAll()
        req = self._get_request("cells/capacities")
        req.environ["nova.context"] = self.context
        res_dict = self.controller.capacities(req, 'cell_name')
        self.assertEqual(response, res_dict['cell']['capacities'])

    def test_sync_instances(self):
        call_info = {}

        def sync_instances(self, context, **kwargs):
            call_info['project_id'] = kwargs.get('project_id')
            call_info['updated_since'] = kwargs.get('updated_since')
            call_info['deleted'] = kwargs.get('deleted')

        self.stubs.Set(cells_rpcapi.CellsAPI, 'sync_instances', sync_instances)

        req = self._get_request("cells/sync_instances")
        body = {}
        self.controller.sync_instances(req, body=body)
        self.assertIsNone(call_info['project_id'])
        self.assertIsNone(call_info['updated_since'])

        body = {'project_id': 'test-project'}
        self.controller.sync_instances(req, body=body)
        self.assertEqual(call_info['project_id'], 'test-project')
        self.assertIsNone(call_info['updated_since'])

        expected = timeutils.utcnow().isoformat()
        if not expected.endswith("+00:00"):
            expected += "+00:00"

        body = {'updated_since': expected}
        self.controller.sync_instances(req, body=body)
        self.assertIsNone(call_info['project_id'])
        self.assertEqual(call_info['updated_since'], expected)

        body = {'updated_since': 'skjdfkjsdkf'}
        self.assertRaises(exc.HTTPBadRequest,
                self.controller.sync_instances, req, body=body)

        body = {'deleted': False}
        self.controller.sync_instances(req, body=body)
        self.assertIsNone(call_info['project_id'])
        self.assertIsNone(call_info['updated_since'])
        self.assertEqual(call_info['deleted'], False)

        body = {'deleted': 'False'}
        self.controller.sync_instances(req, body=body)
        self.assertIsNone(call_info['project_id'])
        self.assertIsNone(call_info['updated_since'])
        self.assertEqual(call_info['deleted'], False)

        body = {'deleted': 'True'}
        self.controller.sync_instances(req, body=body)
        self.assertIsNone(call_info['project_id'])
        self.assertIsNone(call_info['updated_since'])
        self.assertEqual(call_info['deleted'], True)

        body = {'deleted': 'foo'}
        self.assertRaises(exc.HTTPBadRequest,
                self.controller.sync_instances, req, body=body)

        body = {'foo': 'meow'}
        self.assertRaises(exc.HTTPBadRequest,
                self.controller.sync_instances, req, body=body)

    def test_cells_disabled(self):
        self.flags(enable=False, group='cells')

        req = self._get_request("cells")
        self.assertRaises(exc.HTTPNotImplemented,
                self.controller.index, req)

        req = self._get_request("cells/detail")
        self.assertRaises(exc.HTTPNotImplemented,
                self.controller.detail, req)

        req = self._get_request("cells/cell1")
        self.assertRaises(exc.HTTPNotImplemented,
                self.controller.show, req)

        self.assertRaises(exc.HTTPNotImplemented,
                self.controller.delete, req, 'cell999')

        req = self._get_request("cells/cells")
        self.assertRaises(exc.HTTPNotImplemented,
                self.controller.create, req, {})

        req = self._get_request("cells/capacities")
        self.assertRaises(exc.HTTPNotImplemented,
                self.controller.capacities, req)

        req = self._get_request("cells/sync_instances")
        self.assertRaises(exc.HTTPNotImplemented,
                self.controller.sync_instances, req, {})


class TestCellsXMLSerializer(BaseCellsTest):
    def test_multiple_cells(self):
        fixture = {'cells': self._get_all_cell_info()}

        serializer = cells_ext.CellsTemplate()
        output = serializer.serialize(fixture)
        res_tree = etree.XML(output)

        self.assertEqual(res_tree.tag, '{%s}cells' % xmlutil.XMLNS_V10)
        self.assertEqual(len(res_tree), 2)
        self.assertEqual(res_tree[0].tag, '{%s}cell' % xmlutil.XMLNS_V10)
        self.assertEqual(res_tree[1].tag, '{%s}cell' % xmlutil.XMLNS_V10)

    def test_single_cell_with_caps(self):
        cell = {'id': 1,
                'name': 'darksecret',
                'username': 'meow',
                'capabilities': {'cap1': 'a;b',
                                 'cap2': 'c;d'}}
        fixture = {'cell': cell}

        serializer = cells_ext.CellTemplate()
        output = serializer.serialize(fixture)
        res_tree = etree.XML(output)

        self.assertEqual(res_tree.tag, '{%s}cell' % xmlutil.XMLNS_V10)
        self.assertEqual(res_tree.get('name'), 'darksecret')
        self.assertEqual(res_tree.get('username'), 'meow')
        self.assertIsNone(res_tree.get('password'))
        self.assertEqual(len(res_tree), 1)

        child = res_tree[0]
        self.assertEqual(child.tag,
                '{%s}capabilities' % xmlutil.XMLNS_V10)
        for elem in child:
            self.assertIn(elem.tag, ('{%s}cap1' % xmlutil.XMLNS_V10,
                                      '{%s}cap2' % xmlutil.XMLNS_V10))
            if elem.tag == '{%s}cap1' % xmlutil.XMLNS_V10:
                self.assertEqual(elem.text, 'a;b')
            elif elem.tag == '{%s}cap2' % xmlutil.XMLNS_V10:
                self.assertEqual(elem.text, 'c;d')

    def test_single_cell_without_caps(self):
        cell = {'id': 1,
                'username': 'woof',
                'name': 'darksecret'}
        fixture = {'cell': cell}

        serializer = cells_ext.CellTemplate()
        output = serializer.serialize(fixture)
        res_tree = etree.XML(output)

        self.assertEqual(res_tree.tag, '{%s}cell' % xmlutil.XMLNS_V10)
        self.assertEqual(res_tree.get('name'), 'darksecret')
        self.assertEqual(res_tree.get('username'), 'woof')
        self.assertIsNone(res_tree.get('password'))
        self.assertEqual(len(res_tree), 0)


class TestCellsXMLDeserializer(test.NoDBTestCase):
    def test_cell_deserializer(self):
        caps_dict = {'cap1': 'a;b',
                             'cap2': 'c;d'}
        caps_xml = ("<capabilities><cap1>a;b</cap1>"
                "<cap2>c;d</cap2></capabilities>")
        expected = {'cell': {'name': 'testcell1',
                             'type': 'child',
                             'rpc_host': 'localhost',
                             'capabilities': caps_dict}}
        intext = ("<?xml version='1.0' encoding='UTF-8'?>\n"
                "<cell><name>testcell1</name><type>child</type>"
                        "<rpc_host>localhost</rpc_host>"
                        "%s</cell>") % caps_xml
        deserializer = cells_ext.CellDeserializer()
        result = deserializer.deserialize(intext)
        self.assertEqual(dict(body=expected), result)

    def test_with_corrupt_xml(self):
        deserializer = cells_ext.CellDeserializer()
        self.assertRaises(
                exception.MalformedRequestBody,
                deserializer.deserialize,
                utils.killer_xml_body())
