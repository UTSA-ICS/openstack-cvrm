# -*- coding: utf-8 -*-

#    Copyright (C) 2013 Rackspace Hosting All Rights Reserved.
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

import contextlib

from taskflow import exceptions as exc
from taskflow.openstack.common import uuidutils
from taskflow.persistence import logbook
from taskflow import states
from taskflow.types import failure


class PersistenceTestMixin(object):
    def _get_connection(self):
        raise NotImplementedError()

    def test_logbook_save_retrieve(self):
        lb_id = uuidutils.generate_uuid()
        lb_meta = {'1': 2}
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        lb.meta = lb_meta

        # Should not already exist
        with contextlib.closing(self._get_connection()) as conn:
            self.assertRaises(exc.NotFound, conn.get_logbook, lb_id)
            conn.save_logbook(lb)

        # Make sure we can reload it (and all of its attributes are what
        # we expect them to be).
        with contextlib.closing(self._get_connection()) as conn:
            lb = conn.get_logbook(lb_id)
        self.assertEqual(lb_name, lb.name)
        self.assertEqual(0, len(lb))
        self.assertEqual(lb_meta, lb.meta)
        self.assertIsNone(lb.updated_at)
        self.assertIsNotNone(lb.created_at)

    def test_flow_detail_save(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)

        # Ensure we can't save it since its owning logbook hasn't been
        # saved (flow details can not exist on their own without a connection
        # to a logbook).
        with contextlib.closing(self._get_connection()) as conn:
            self.assertRaises(exc.NotFound, conn.get_logbook, lb_id)
            self.assertRaises(exc.NotFound, conn.update_flow_details, fd)

        # Ok now we should be able to save both.
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)

    def test_flow_detail_meta_update(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        fd.meta = {'test': 42}
        lb.add(fd)

        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)

        fd.meta['test'] = 43
        with contextlib.closing(self._get_connection()) as conn:
            conn.update_flow_details(fd)
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
        fd2 = lb2.find(fd.uuid)
        self.assertEqual(fd2.meta.get('test'), 43)

    def test_task_detail_save(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        td = logbook.TaskDetail("detail-1", uuid=uuidutils.generate_uuid())
        fd.add(td)

        # Ensure we can't save it since its owning logbook hasn't been
        # saved (flow details/task details can not exist on their own without
        # their parent existing).
        with contextlib.closing(self._get_connection()) as conn:
            self.assertRaises(exc.NotFound, conn.update_flow_details, fd)
            self.assertRaises(exc.NotFound, conn.update_atom_details, td)

        # Ok now we should be able to save them.
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)
            conn.update_atom_details(td)

    def test_task_detail_meta_update(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        td = logbook.TaskDetail("detail-1", uuid=uuidutils.generate_uuid())
        td.meta = {'test': 42}
        fd.add(td)

        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)
            conn.update_atom_details(td)

        td.meta['test'] = 43
        with contextlib.closing(self._get_connection()) as conn:
            conn.update_atom_details(td)

        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
        fd2 = lb2.find(fd.uuid)
        td2 = fd2.find(td.uuid)
        self.assertEqual(td2.meta.get('test'), 43)
        self.assertIsInstance(td2, logbook.TaskDetail)

    def test_task_detail_with_failure(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        td = logbook.TaskDetail("detail-1", uuid=uuidutils.generate_uuid())

        try:
            raise RuntimeError('Woot!')
        except Exception:
            td.failure = failure.Failure()

        fd.add(td)

        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)
            conn.update_atom_details(td)

        # Read failure back
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
        fd2 = lb2.find(fd.uuid)
        td2 = fd2.find(td.uuid)
        self.assertEqual(td2.failure.exception_str, 'Woot!')
        self.assertIs(td2.failure.check(RuntimeError), RuntimeError)
        self.assertEqual(td2.failure.traceback_str, td.failure.traceback_str)
        self.assertIsInstance(td2, logbook.TaskDetail)

    def test_logbook_merge_flow_detail(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
        lb2 = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd2 = logbook.FlowDetail('test2', uuid=uuidutils.generate_uuid())
        lb2.add(fd2)
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb2)
        with contextlib.closing(self._get_connection()) as conn:
            lb3 = conn.get_logbook(lb_id)
            self.assertEqual(2, len(lb3))

    def test_logbook_add_flow_detail(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
            self.assertEqual(1, len(lb2))
            self.assertEqual(1, len(lb))
            self.assertEqual(fd.name, lb2.find(fd.uuid).name)

    def test_logbook_add_task_detail(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        td = logbook.TaskDetail("detail-1", uuid=uuidutils.generate_uuid())
        td.version = '4.2'
        fd.add(td)
        lb.add(fd)
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
            self.assertEqual(1, len(lb2))
            tasks = 0
            for fd in lb:
                tasks += len(fd)
            self.assertEqual(1, tasks)
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
            fd2 = lb2.find(fd.uuid)
            td2 = fd2.find(td.uuid)
            self.assertIsNot(td2, None)
            self.assertEqual(td2.name, 'detail-1')
            self.assertEqual(td2.version, '4.2')
            self.assertEqual(td2.intention, states.EXECUTE)

    def test_logbook_delete(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        with contextlib.closing(self._get_connection()) as conn:
            self.assertRaises(exc.NotFound, conn.destroy_logbook, lb_id)
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
            self.assertIsNotNone(lb2)
        with contextlib.closing(self._get_connection()) as conn:
            conn.destroy_logbook(lb_id)
            self.assertRaises(exc.NotFound, conn.destroy_logbook, lb_id)

    def test_task_detail_retry_type_(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        rd = logbook.RetryDetail("detail-1", uuid=uuidutils.generate_uuid())
        rd.intention = states.REVERT
        fd.add(rd)

        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)
            conn.update_atom_details(rd)

        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
        fd2 = lb2.find(fd.uuid)
        rd2 = fd2.find(rd.uuid)
        self.assertEqual(rd2.intention, states.REVERT)
        self.assertIsInstance(rd2, logbook.RetryDetail)

    def test_retry_detail_save_with_task_failure(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        rd = logbook.RetryDetail("retry-1", uuid=uuidutils.generate_uuid())
        fail = failure.Failure.from_exception(RuntimeError('fail'))
        rd.results.append((42, {'some-task': fail}))
        fd.add(rd)

        # save it
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)
            conn.update_atom_details(rd)

        # now read it back
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
        fd2 = lb2.find(fd.uuid)
        rd2 = fd2.find(rd.uuid)
        self.assertIsInstance(rd2, logbook.RetryDetail)
        fail2 = rd2.results[0][1].get('some-task')
        self.assertIsInstance(fail2, failure.Failure)
        self.assertTrue(fail.matches(fail2))

    def test_retry_detail_save_intention(self):
        lb_id = uuidutils.generate_uuid()
        lb_name = 'lb-%s' % (lb_id)
        lb = logbook.LogBook(name=lb_name, uuid=lb_id)
        fd = logbook.FlowDetail('test', uuid=uuidutils.generate_uuid())
        lb.add(fd)
        rd = logbook.RetryDetail("retry-1", uuid=uuidutils.generate_uuid())
        fd.add(rd)

        # save it
        with contextlib.closing(self._get_connection()) as conn:
            conn.save_logbook(lb)
            conn.update_flow_details(fd)
            conn.update_atom_details(rd)

        # change intention and save
        rd.intention = states.REVERT
        with contextlib.closing(self._get_connection()) as conn:
            conn.update_atom_details(rd)

        # now read it back
        with contextlib.closing(self._get_connection()) as conn:
            lb2 = conn.get_logbook(lb_id)
        fd2 = lb2.find(fd.uuid)
        rd2 = fd2.find(rd.uuid)
        self.assertEqual(rd2.intention, states.REVERT)
        self.assertIsInstance(rd2, logbook.RetryDetail)
