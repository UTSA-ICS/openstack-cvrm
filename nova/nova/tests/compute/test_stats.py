# Copyright (c) 2012 OpenStack Foundation
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

"""Tests for compute node stats."""

from nova.compute import stats
from nova.compute import task_states
from nova.compute import vm_states
from nova import test


class StatsTestCase(test.NoDBTestCase):
    def setUp(self):
        super(StatsTestCase, self).setUp()
        self.stats = stats.Stats()

    def _create_instance(self, values=None):
        instance = {
            "os_type": "Linux",
            "project_id": "1234",
            "task_state": None,
            "vm_state": vm_states.BUILDING,
            "vcpus": 1,
            "uuid": "12-34-56-78-90",
        }
        if values:
            instance.update(values)
        return instance

    def test_os_type_count(self):
        os_type = "Linux"
        self.assertEqual(0, self.stats.num_os_type(os_type))
        self.stats._increment("num_os_type_" + os_type)
        self.stats._increment("num_os_type_" + os_type)
        self.stats._increment("num_os_type_Vax")
        self.assertEqual(2, self.stats.num_os_type(os_type))
        self.stats["num_os_type_" + os_type] -= 1
        self.assertEqual(1, self.stats.num_os_type(os_type))

    def test_update_project_count(self):
        proj_id = "1234"

        def _get():
            return self.stats.num_instances_for_project(proj_id)

        self.assertEqual(0, _get())
        self.stats._increment("num_proj_" + proj_id)
        self.assertEqual(1, _get())
        self.stats["num_proj_" + proj_id] -= 1
        self.assertEqual(0, _get())

    def test_instance_count(self):
        self.assertEqual(0, self.stats.num_instances)
        for i in range(5):
            self.stats._increment("num_instances")
        self.stats["num_instances"] -= 1
        self.assertEqual(4, self.stats.num_instances)

    def test_add_stats_for_instance(self):
        instance = {
            "os_type": "Linux",
            "project_id": "1234",
            "task_state": None,
            "vm_state": vm_states.BUILDING,
            "vcpus": 3,
            "uuid": "12-34-56-78-90",
        }
        self.stats.update_stats_for_instance(instance)

        instance = {
            "os_type": "FreeBSD",
            "project_id": "1234",
            "task_state": task_states.SCHEDULING,
            "vm_state": None,
            "vcpus": 1,
            "uuid": "23-45-67-89-01",
        }
        self.stats.update_stats_for_instance(instance)

        instance = {
            "os_type": "Linux",
            "project_id": "2345",
            "task_state": task_states.SCHEDULING,
            "vm_state": vm_states.BUILDING,
            "vcpus": 2,
            "uuid": "34-56-78-90-12",
        }
        self.stats.update_stats_for_instance(instance)

        self.assertEqual(2, self.stats.num_os_type("Linux"))
        self.assertEqual(1, self.stats.num_os_type("FreeBSD"))

        self.assertEqual(2, self.stats.num_instances_for_project("1234"))
        self.assertEqual(1, self.stats.num_instances_for_project("2345"))

        self.assertEqual(1, self.stats["num_task_None"])
        self.assertEqual(2, self.stats["num_task_" + task_states.SCHEDULING])

        self.assertEqual(1, self.stats["num_vm_None"])
        self.assertEqual(2, self.stats["num_vm_" + vm_states.BUILDING])

        self.assertEqual(6, self.stats.num_vcpus_used)

    def test_calculate_workload(self):
        self.stats._increment("num_task_None")
        self.stats._increment("num_task_" + task_states.SCHEDULING)
        self.stats._increment("num_task_" + task_states.SCHEDULING)
        self.assertEqual(2, self.stats.calculate_workload())

    def test_update_stats_for_instance_no_change(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        self.stats.update_stats_for_instance(instance)  # no change
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(1, self.stats["num_task_None"])
        self.assertEqual(1, self.stats["num_vm_" + vm_states.BUILDING])

    def test_update_stats_for_instance_vm_change(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        instance["vm_state"] = vm_states.PAUSED
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project(1234))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(0, self.stats["num_vm_%s" % vm_states.BUILDING])
        self.assertEqual(1, self.stats["num_vm_%s" % vm_states.PAUSED])

    def test_update_stats_for_instance_task_change(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        instance["task_state"] = task_states.REBUILDING
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats.num_instances)
        self.assertEqual(1, self.stats.num_instances_for_project("1234"))
        self.assertEqual(1, self.stats["num_os_type_Linux"])
        self.assertEqual(0, self.stats["num_task_None"])
        self.assertEqual(1, self.stats["num_task_%s" % task_states.REBUILDING])

    def test_update_stats_for_instance_deleted(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(1, self.stats["num_proj_1234"])

        instance["vm_state"] = vm_states.DELETED
        self.stats.update_stats_for_instance(instance)

        self.assertEqual(0, self.stats.num_instances)
        self.assertEqual(0, self.stats.num_instances_for_project("1234"))
        self.assertEqual(0, self.stats.num_os_type("Linux"))
        self.assertEqual(0, self.stats["num_vm_" + vm_states.BUILDING])
        self.assertEqual(0, self.stats.num_vcpus_used)

    def test_io_workload(self):
        vms = [vm_states.ACTIVE, vm_states.BUILDING, vm_states.PAUSED]
        tasks = [task_states.RESIZE_MIGRATING, task_states.REBUILDING,
                 task_states.RESIZE_PREP, task_states.IMAGE_SNAPSHOT,
                 task_states.IMAGE_BACKUP, task_states.RESCUING]

        for state in vms:
            self.stats._increment("num_vm_" + state)
        for state in tasks:
            self.stats._increment("num_task_" + state)

        self.assertEqual(6, self.stats.io_workload)

    def test_io_workload_saved_to_stats(self):
        values = {'task_state': task_states.RESIZE_MIGRATING}
        instance = self._create_instance(values)
        self.stats.update_stats_for_instance(instance)
        self.assertEqual(2, self.stats["io_workload"])

    def test_clear(self):
        instance = self._create_instance()
        self.stats.update_stats_for_instance(instance)

        self.assertNotEqual(0, len(self.stats))
        self.assertEqual(1, len(self.stats.states))
        self.stats.clear()

        self.assertEqual(0, len(self.stats))
        self.assertEqual(0, len(self.stats.states))
