# Copyright (c) 2012-2013 Rackspace Hosting
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
Unit Tests for cells scheduler filters.
"""

from nova.cells import filters
from nova import context
from nova.db.sqlalchemy import models
from nova import test
from nova.tests.cells import fakes


class FiltersTestCase(test.NoDBTestCase):
    """Makes sure the proper filters are in the directory."""

    def test_all_filters(self):
        filter_classes = filters.all_filters()
        class_names = [cls.__name__ for cls in filter_classes]
        self.assertIn("TargetCellFilter", class_names)


class _FilterTestClass(test.NoDBTestCase):
    """Base class for testing individual filter plugins."""
    filter_cls_name = None

    def setUp(self):
        super(_FilterTestClass, self).setUp()
        fakes.init(self)
        self.msg_runner = fakes.get_message_runner('api-cell')
        self.scheduler = self.msg_runner.scheduler
        self.my_cell_state = self.msg_runner.state_manager.get_my_state()
        self.filter_handler = filters.CellFilterHandler()
        self.filter_classes = self.filter_handler.get_matching_classes(
                [self.filter_cls_name])
        self.context = context.RequestContext('fake', 'fake',
                                              is_admin=True)

    def _filter_cells(self, cells, filter_properties):
        return self.filter_handler.get_filtered_objects(self.filter_classes,
                                                        cells,
                                                        filter_properties)


class ImagePropertiesFilter(_FilterTestClass):
    filter_cls_name = \
        'nova.cells.filters.image_properties.ImagePropertiesFilter'

    def setUp(self):
        super(ImagePropertiesFilter, self).setUp()
        self.cell1 = models.Cell()
        self.cell2 = models.Cell()
        self.cell3 = models.Cell()
        self.cells = [self.cell1, self.cell2, self.cell3]
        for cell in self.cells:
            cell.capabilities = {}
        self.filter_props = {'context': self.context, 'request_spec': {}}

    def test_missing_image_properties(self):
        self.assertEqual(self.cells,
                         self._filter_cells(self.cells, self.filter_props))

    def test_missing_hypervisor_version_requires(self):
        self.filter_props['request_spec'] = {'image': {'properties': {}}}
        for cell in self.cells:
            cell.capabilities = {"prominent_hypervisor_version": [u"6.2"]}
        self.assertEqual(self.cells,
                         self._filter_cells(self.cells, self.filter_props))

    def test_missing_hypervisor_version_in_cells(self):
        image = {'properties': {'hypervisor_version_requires': '>6.2.1'}}
        self.filter_props['request_spec'] = {'image': image}
        self.assertEqual(self.cells,
                         self._filter_cells(self.cells, self.filter_props))

    def test_cells_matching_hypervisor_version(self):
        image = {'properties': {'hypervisor_version_requires': '>6.0, <=6.3'}}
        self.filter_props['request_spec'] = {'image': image}

        self.cell1.capabilities = {"prominent_hypervisor_version": [u"6.2"]}
        self.cell2.capabilities = {"prominent_hypervisor_version": [u"6.3"]}
        self.cell3.capabilities = {"prominent_hypervisor_version": [u"6.0"]}

        self.assertEqual([self.cell1, self.cell2],
                         self._filter_cells(self.cells, self.filter_props))


class TestTargetCellFilter(_FilterTestClass):
    filter_cls_name = 'nova.cells.filters.target_cell.TargetCellFilter'

    def test_missing_scheduler_hints(self):
        cells = [1, 2, 3]
        # No filtering
        filter_props = {'context': self.context}
        self.assertEqual(cells, self._filter_cells(cells, filter_props))

    def test_no_target_cell_hint(self):
        cells = [1, 2, 3]
        filter_props = {'scheduler_hints': {},
                        'context': self.context}
        # No filtering
        self.assertEqual(cells, self._filter_cells(cells, filter_props))

    def test_target_cell_specified_me(self):
        cells = [1, 2, 3]
        target_cell = 'fake!cell!path'
        current_cell = 'fake!cell!path'
        filter_props = {'scheduler_hints': {'target_cell': target_cell},
                        'routing_path': current_cell,
                        'scheduler': self.scheduler,
                        'context': self.context}
        # Only myself in the list.
        self.assertEqual([self.my_cell_state],
                         self._filter_cells(cells, filter_props))

    def test_target_cell_specified_me_but_not_admin(self):
        ctxt = context.RequestContext('fake', 'fake')
        cells = [1, 2, 3]
        target_cell = 'fake!cell!path'
        current_cell = 'fake!cell!path'
        filter_props = {'scheduler_hints': {'target_cell': target_cell},
                        'routing_path': current_cell,
                        'scheduler': self.scheduler,
                        'context': ctxt}
        # No filtering, because not an admin.
        self.assertEqual(cells, self._filter_cells(cells, filter_props))

    def test_target_cell_specified_not_me(self):
        info = {}

        def _fake_sched_run_instance(ctxt, cell, sched_kwargs):
            info['ctxt'] = ctxt
            info['cell'] = cell
            info['sched_kwargs'] = sched_kwargs

        self.stubs.Set(self.msg_runner, 'schedule_run_instance',
                       _fake_sched_run_instance)
        cells = [1, 2, 3]
        target_cell = 'fake!cell!path'
        current_cell = 'not!the!same'
        filter_props = {'scheduler_hints': {'target_cell': target_cell},
                        'routing_path': current_cell,
                        'scheduler': self.scheduler,
                        'context': self.context,
                        'host_sched_kwargs': 'meow',
                        'cell_scheduler_method': 'schedule_run_instance'}
        # None is returned to bypass further scheduling.
        self.assertIsNone(self._filter_cells(cells, filter_props))
        # The filter should have re-scheduled to the child cell itself.
        expected_info = {'ctxt': self.context,
                         'cell': 'fake!cell!path',
                         'sched_kwargs': 'meow'}
        self.assertEqual(expected_info, info)
