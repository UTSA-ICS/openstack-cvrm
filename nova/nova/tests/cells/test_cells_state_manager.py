# Copyright (c) 2013 Rackspace Hosting
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
"""
Tests For CellStateManager
"""

import mock
import six

from oslo.config import cfg

from nova.cells import state
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova.openstack.common import fileutils
from nova import test


FAKE_COMPUTES = [
    ('host1', 1024, 100, 0, 0),
    ('host2', 1024, 100, -1, -1),
    ('host3', 1024, 100, 1024, 100),
    ('host4', 1024, 100, 300, 30),
]

# NOTE(alaski): It's important to have multiple types that end up having the
# same memory and disk requirements.  So two types need the same first value,
# and two need the second and third values to add up to the same thing.
FAKE_ITYPES = [
    (0, 0, 0),
    (50, 12, 13),
    (50, 2, 4),
    (10, 20, 5),
]


def _fake_compute_node_get_all(context):
    def _node(host, total_mem, total_disk, free_mem, free_disk):
        service = {'host': host, 'disabled': False}
        return {'service': service,
                'memory_mb': total_mem,
                'local_gb': total_disk,
                'free_ram_mb': free_mem,
                'free_disk_gb': free_disk}

    return [_node(*fake) for fake in FAKE_COMPUTES]


def _fake_instance_type_all(context):
    def _type(mem, root, eph):
        return {'root_gb': root,
                'ephemeral_gb': eph,
                'memory_mb': mem}

    return [_type(*fake) for fake in FAKE_ITYPES]


class TestCellsStateManager(test.TestCase):

    def setUp(self):
        super(TestCellsStateManager, self).setUp()

        self.stubs.Set(db, 'compute_node_get_all', _fake_compute_node_get_all)
        self.stubs.Set(db, 'flavor_get_all', _fake_instance_type_all)

    def test_cells_config_not_found(self):
        self.flags(cells_config='no_such_file_exists.conf', group='cells')
        e = self.assertRaises(cfg.ConfigFilesNotFoundError,
                              state.CellStateManager)
        self.assertEqual(['no_such_file_exists.conf'], e.config_files)

    @mock.patch.object(cfg.ConfigOpts, 'find_file')
    @mock.patch.object(fileutils, 'read_cached_file')
    def test_filemanager_returned(self, mock_read_cached_file, mock_find_file):
        mock_find_file.return_value = "/etc/nova/cells.json"
        mock_read_cached_file.return_value = (False, six.StringIO({}))
        self.flags(cells_config='cells.json', group='cells')
        self.assertIsInstance(state.CellStateManager(),
                              state.CellStateManagerFile)

    def test_dbmanager_returned(self):
        self.assertIsInstance(state.CellStateManager(),
                              state.CellStateManagerDB)

    def test_capacity_no_reserve(self):
        # utilize entire cell
        cap = self._capacity(0.0)

        cell_free_ram = sum(compute[3] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(compute[4] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])

        units = cell_free_ram / 50
        self.assertEqual(units, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        units = 5  # 4 on host 3, 1 on host4
        self.assertEqual(units, cap['disk_free']['units_by_mb'][str(sz)])

    def test_capacity_full_reserve(self):
        # reserve the entire cell. (utilize zero percent)
        cap = self._capacity(100.0)

        cell_free_ram = sum(compute[3] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(compute[4] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        self.assertEqual(0, cap['disk_free']['units_by_mb'][str(sz)])

    def test_capacity_part_reserve(self):
        # utilize half the cell's free capacity
        cap = self._capacity(50.0)

        cell_free_ram = sum(compute[3] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_ram, cap['ram_free']['total_mb'])

        cell_free_disk = 1024 * sum(compute[4] for compute in FAKE_COMPUTES)
        self.assertEqual(cell_free_disk, cap['disk_free']['total_mb'])

        self.assertEqual(0, cap['ram_free']['units_by_mb']['0'])
        self.assertEqual(0, cap['disk_free']['units_by_mb']['0'])

        units = 10  # 10 from host 3
        self.assertEqual(units, cap['ram_free']['units_by_mb']['50'])

        sz = 25 * 1024
        units = 2  # 2 on host 3
        self.assertEqual(units, cap['disk_free']['units_by_mb'][str(sz)])

    def _get_state_manager(self, reserve_percent=0.0):
        self.flags(reserve_percent=reserve_percent, group='cells')
        return state.CellStateManager()

    def _capacity(self, reserve_percent):
        state_manager = self._get_state_manager(reserve_percent)
        my_state = state_manager.get_my_state()
        return my_state.capacities


class TestCellsGetCapacity(TestCellsStateManager):
    def setUp(self):
        super(TestCellsGetCapacity, self).setUp()
        self.capacities = {"ram_free": 1234}
        self.state_manager = self._get_state_manager()
        cell = models.Cell(name="cell_name")
        other_cell = models.Cell(name="other_cell_name")
        cell.capacities = self.capacities
        other_cell.capacities = self.capacities
        self.stubs.Set(self.state_manager, 'child_cells',
                        {"cell_name": cell,
                        "other_cell_name": other_cell})

    def test_get_cell_capacity_for_all_cells(self):
        self.stubs.Set(self.state_manager.my_cell_state, 'capacities',
                                                        self.capacities)
        capacities = self.state_manager.get_capacities()
        self.assertEqual({"ram_free": 3702}, capacities)

    def test_get_cell_capacity_for_the_parent_cell(self):
        self.stubs.Set(self.state_manager.my_cell_state, 'capacities',
                                                        self.capacities)
        capacities = self.state_manager.\
                     get_capacities(self.state_manager.my_cell_state.name)
        self.assertEqual({"ram_free": 3702}, capacities)

    def test_get_cell_capacity_for_a_cell(self):
        self.assertEqual(self.capacities,
                self.state_manager.get_capacities(cell_name="cell_name"))

    def test_get_cell_capacity_for_non_existing_cell(self):
        self.assertRaises(exception.CellNotFound,
                          self.state_manager.get_capacities,
                          cell_name="invalid_cell_name")


class FakeCellStateManager(object):
    def __init__(self):
        self.called = []

    def _cell_data_sync(self, force=False):
        self.called.append(('_cell_data_sync', force))


class TestSyncDecorators(test.TestCase):
    def test_sync_before(self):
        manager = FakeCellStateManager()

        def test(inst, *args, **kwargs):
            self.assertEqual(inst, manager)
            self.assertEqual(args, (1, 2, 3))
            self.assertEqual(kwargs, dict(a=4, b=5, c=6))
            return 'result'
        wrapper = state.sync_before(test)

        result = wrapper(manager, 1, 2, 3, a=4, b=5, c=6)

        self.assertEqual(result, 'result')
        self.assertEqual(manager.called, [('_cell_data_sync', False)])

    def test_sync_after(self):
        manager = FakeCellStateManager()

        def test(inst, *args, **kwargs):
            self.assertEqual(inst, manager)
            self.assertEqual(args, (1, 2, 3))
            self.assertEqual(kwargs, dict(a=4, b=5, c=6))
            return 'result'
        wrapper = state.sync_after(test)

        result = wrapper(manager, 1, 2, 3, a=4, b=5, c=6)

        self.assertEqual(result, 'result')
        self.assertEqual(manager.called, [('_cell_data_sync', True)])
