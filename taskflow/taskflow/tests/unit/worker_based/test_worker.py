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

from taskflow.engines.worker_based import endpoint
from taskflow.engines.worker_based import worker
from taskflow import test
from taskflow.test import mock
from taskflow.tests import utils
from taskflow.utils import reflection


class TestWorker(test.MockTestCase):

    def setUp(self):
        super(TestWorker, self).setUp()
        self.task_cls = utils.DummyTask
        self.task_name = reflection.get_class_name(self.task_cls)
        self.broker_url = 'test-url'
        self.exchange = 'test-exchange'
        self.topic = 'test-topic'
        self.threads_count = 5
        self.endpoint_count = 22

        # patch classes
        self.executor_mock, self.executor_inst_mock = self.patchClass(
            worker.futures, 'ThreadPoolExecutor', attach_as='executor')
        self.server_mock, self.server_inst_mock = self.patchClass(
            worker.server, 'Server')

        # other mocking
        self.threads_count_mock = self.patch(
            'taskflow.engines.worker_based.worker.tu.get_optimal_thread_count')
        self.threads_count_mock.return_value = self.threads_count

    def worker(self, reset_master_mock=False, **kwargs):
        worker_kwargs = dict(exchange=self.exchange,
                             topic=self.topic,
                             tasks=[],
                             url=self.broker_url)
        worker_kwargs.update(kwargs)
        w = worker.Worker(**worker_kwargs)
        if reset_master_mock:
            self.resetMasterMock()
        return w

    def test_creation(self):
        self.worker()

        master_mock_calls = [
            mock.call.executor_class(self.threads_count),
            mock.call.Server(self.topic, self.exchange,
                             self.executor_inst_mock, [], url=self.broker_url)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_creation_with_custom_threads_count(self):
        self.worker(threads_count=10)

        master_mock_calls = [
            mock.call.executor_class(10),
            mock.call.Server(self.topic, self.exchange,
                             self.executor_inst_mock, [], url=self.broker_url)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_creation_with_negative_threads_count(self):
        self.assertRaises(ValueError, self.worker, threads_count=-10)

    def test_creation_with_custom_executor(self):
        executor_mock = mock.MagicMock(name='executor')
        self.worker(executor=executor_mock)

        master_mock_calls = [
            mock.call.Server(self.topic, self.exchange, executor_mock, [],
                             url=self.broker_url)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_run_with_no_tasks(self):
        self.worker(reset_master_mock=True).run()

        master_mock_calls = [
            mock.call.server.start()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_run_with_tasks(self):
        self.worker(reset_master_mock=True,
                    tasks=['taskflow.tests.utils:DummyTask']).run()

        master_mock_calls = [
            mock.call.server.start()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_run_with_custom_executor(self):
        executor_mock = mock.MagicMock(name='executor')
        self.worker(reset_master_mock=True,
                    executor=executor_mock).run()

        master_mock_calls = [
            mock.call.server.start()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_wait(self):
        w = self.worker(reset_master_mock=True)
        w.run()
        w.wait()

        master_mock_calls = [
            mock.call.server.start(),
            mock.call.server.wait()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_stop(self):
        self.worker(reset_master_mock=True).stop()

        master_mock_calls = [
            mock.call.server.stop(),
            mock.call.executor.shutdown()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_derive_endpoints_from_string_tasks(self):
        endpoints = worker.Worker._derive_endpoints(
            ['taskflow.tests.utils:DummyTask'])

        self.assertEqual(len(endpoints), 1)
        self.assertIsInstance(endpoints[0], endpoint.Endpoint)
        self.assertEqual(endpoints[0].name, self.task_name)

    def test_derive_endpoints_from_string_modules(self):
        endpoints = worker.Worker._derive_endpoints(['taskflow.tests.utils'])

        self.assertEqual(len(endpoints), self.endpoint_count)

    def test_derive_endpoints_from_string_non_existent_module(self):
        tasks = ['non.existent.module']

        self.assertRaises(ImportError, worker.Worker._derive_endpoints, tasks)

    def test_derive_endpoints_from_string_non_existent_task(self):
        tasks = ['non.existent.module:Task']

        self.assertRaises(ImportError, worker.Worker._derive_endpoints, tasks)

    def test_derive_endpoints_from_string_non_task_class(self):
        tasks = ['taskflow.tests.utils:FakeTask']

        self.assertRaises(TypeError, worker.Worker._derive_endpoints, tasks)

    def test_derive_endpoints_from_tasks(self):
        endpoints = worker.Worker._derive_endpoints([self.task_cls])

        self.assertEqual(len(endpoints), 1)
        self.assertIsInstance(endpoints[0], endpoint.Endpoint)
        self.assertEqual(endpoints[0].name, self.task_name)

    def test_derive_endpoints_from_non_task_class(self):
        self.assertRaises(TypeError, worker.Worker._derive_endpoints,
                          [utils.FakeTask])

    def test_derive_endpoints_from_modules(self):
        endpoints = worker.Worker._derive_endpoints([utils])

        self.assertEqual(len(endpoints), self.endpoint_count)

    def test_derive_endpoints_unexpected_task_type(self):
        self.assertRaises(TypeError, worker.Worker._derive_endpoints, [111])
