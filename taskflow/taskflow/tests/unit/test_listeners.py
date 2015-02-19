# -*- coding: utf-8 -*-

#    Copyright (C) 2014 Yahoo! Inc. All Rights Reserved.
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
import logging
import time

import taskflow.engines
from taskflow import exceptions as exc
from taskflow.listeners import logging as logging_listeners
from taskflow.listeners import timing
from taskflow.patterns import linear_flow as lf
from taskflow.persistence.backends import impl_memory
from taskflow import task
from taskflow import test
from taskflow.test import mock
from taskflow.tests import utils as test_utils
from taskflow.utils import persistence_utils
from taskflow.utils import reflection


_LOG_LEVELS = frozenset([
    logging.CRITICAL,
    logging.DEBUG,
    logging.ERROR,
    logging.INFO,
    logging.NOTSET,
    logging.WARNING,
])


class SleepyTask(task.Task):
    def __init__(self, name, sleep_for=0.0):
        super(SleepyTask, self).__init__(name=name)
        self._sleep_for = float(sleep_for)

    def execute(self):
        if self._sleep_for <= 0:
            return
        else:
            time.sleep(self._sleep_for)


class EngineMakerMixin(object):
    def _make_engine(self, flow, flow_detail=None, backend=None):
        e = taskflow.engines.load(flow,
                                  flow_detail=flow_detail,
                                  backend=backend)
        e.compile()
        e.prepare()
        return e


class TestTimingListener(test.TestCase, EngineMakerMixin):
    def test_duration(self):
        with contextlib.closing(impl_memory.MemoryBackend()) as be:
            flow = lf.Flow("test")
            flow.add(SleepyTask("test-1", sleep_for=0.1))
            (lb, fd) = persistence_utils.temporary_flow_detail(be)
            e = self._make_engine(flow, fd, be)
            with timing.TimingListener(e):
                e.run()
            t_uuid = e.storage.get_atom_uuid("test-1")
            td = fd.find(t_uuid)
            self.assertIsNotNone(td)
            self.assertIsNotNone(td.meta)
            self.assertIn('duration', td.meta)
            self.assertGreaterEqual(0.1, td.meta['duration'])

    @mock.patch.object(timing.LOG, 'warn')
    def test_record_ending_exception(self, mocked_warn):
        with contextlib.closing(impl_memory.MemoryBackend()) as be:
            flow = lf.Flow("test")
            flow.add(test_utils.TaskNoRequiresNoReturns("test-1"))
            (lb, fd) = persistence_utils.temporary_flow_detail(be)
            e = self._make_engine(flow, fd, be)
            timing_listener = timing.TimingListener(e)
            with mock.patch.object(timing_listener._engine.storage,
                                   'update_atom_metadata') as mocked_uam:
                mocked_uam.side_effect = exc.StorageFailure('Woot!')
                with timing_listener:
                    e.run()
        mocked_warn.assert_called_once_with(mock.ANY, mock.ANY, 'test-1',
                                            exc_info=True)


class TestLoggingListeners(test.TestCase, EngineMakerMixin):
    def _make_logger(self, level=logging.DEBUG):
        log = logging.getLogger(
            reflection.get_callable_name(self._get_test_method()))
        log.propagate = False
        for handler in reversed(log.handlers):
            log.removeHandler(handler)
        handler = test.CapturingLoggingHandler(level=level)
        log.addHandler(handler)
        log.setLevel(level)
        self.addCleanup(handler.reset)
        self.addCleanup(log.removeHandler, handler)
        return (log, handler)

    def test_basic(self):
        flow = lf.Flow("test")
        flow.add(test_utils.TaskNoRequiresNoReturns("test-1"))
        e = self._make_engine(flow)
        log, handler = self._make_logger()
        with logging_listeners.LoggingListener(e, log=log):
            e.run()
        self.assertGreater(0, handler.counts[logging.DEBUG])
        for levelno in _LOG_LEVELS - set([logging.DEBUG]):
            self.assertEqual(0, handler.counts[levelno])
        self.assertEqual([], handler.exc_infos)

    def test_basic_customized(self):
        flow = lf.Flow("test")
        flow.add(test_utils.TaskNoRequiresNoReturns("test-1"))
        e = self._make_engine(flow)
        log, handler = self._make_logger()
        listener = logging_listeners.LoggingListener(
            e, log=log, level=logging.INFO)
        with listener:
            e.run()
        self.assertGreater(0, handler.counts[logging.INFO])
        for levelno in _LOG_LEVELS - set([logging.INFO]):
            self.assertEqual(0, handler.counts[levelno])
        self.assertEqual([], handler.exc_infos)

    def test_basic_failure(self):
        flow = lf.Flow("test")
        flow.add(test_utils.TaskWithFailure("test-1"))
        e = self._make_engine(flow)
        log, handler = self._make_logger()
        with logging_listeners.LoggingListener(e, log=log):
            self.assertRaises(RuntimeError, e.run)
        self.assertGreater(0, handler.counts[logging.DEBUG])
        for levelno in _LOG_LEVELS - set([logging.DEBUG]):
            self.assertEqual(0, handler.counts[levelno])
        self.assertEqual(1, len(handler.exc_infos))

    def test_dynamic(self):
        flow = lf.Flow("test")
        flow.add(test_utils.TaskNoRequiresNoReturns("test-1"))
        e = self._make_engine(flow)
        log, handler = self._make_logger()
        with logging_listeners.DynamicLoggingListener(e, log=log):
            e.run()
        self.assertGreater(0, handler.counts[logging.DEBUG])
        for levelno in _LOG_LEVELS - set([logging.DEBUG]):
            self.assertEqual(0, handler.counts[levelno])
        self.assertEqual([], handler.exc_infos)

    def test_dynamic_failure(self):
        flow = lf.Flow("test")
        flow.add(test_utils.TaskWithFailure("test-1"))
        e = self._make_engine(flow)
        log, handler = self._make_logger()
        with logging_listeners.DynamicLoggingListener(e, log=log):
            self.assertRaises(RuntimeError, e.run)
        self.assertGreater(0, handler.counts[logging.WARNING])
        self.assertGreater(0, handler.counts[logging.DEBUG])
        self.assertEqual(1, len(handler.exc_infos))
        for levelno in _LOG_LEVELS - set([logging.DEBUG, logging.WARNING]):
            self.assertEqual(0, handler.counts[levelno])

    def test_dynamic_failure_customized_level(self):
        flow = lf.Flow("test")
        flow.add(test_utils.TaskWithFailure("test-1"))
        e = self._make_engine(flow)
        log, handler = self._make_logger()
        listener = logging_listeners.DynamicLoggingListener(
            e, log=log, failure_level=logging.ERROR)
        with listener:
            self.assertRaises(RuntimeError, e.run)
        self.assertGreater(0, handler.counts[logging.ERROR])
        self.assertGreater(0, handler.counts[logging.DEBUG])
        self.assertEqual(1, len(handler.exc_infos))
        for levelno in _LOG_LEVELS - set([logging.DEBUG, logging.ERROR]):
            self.assertEqual(0, handler.counts[levelno])
