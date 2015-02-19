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

import six

from taskflow.engines.worker_based import endpoint as ep
from taskflow.engines.worker_based import protocol as pr
from taskflow.engines.worker_based import server
from taskflow import test
from taskflow.test import mock
from taskflow.tests import utils
from taskflow.types import failure


class TestServer(test.MockTestCase):

    def setUp(self):
        super(TestServer, self).setUp()
        self.server_topic = 'server-topic'
        self.server_exchange = 'server-exchange'
        self.broker_url = 'test-url'
        self.task = utils.TaskOneArgOneReturn()
        self.task_uuid = 'task-uuid'
        self.task_args = {'x': 1}
        self.task_action = 'execute'
        self.reply_to = 'reply-to'
        self.endpoints = [ep.Endpoint(task_cls=utils.TaskOneArgOneReturn),
                          ep.Endpoint(task_cls=utils.TaskWithFailure),
                          ep.Endpoint(task_cls=utils.ProgressingTask)]

        # patch classes
        self.proxy_mock, self.proxy_inst_mock = self.patchClass(
            server.proxy, 'Proxy')
        self.response_mock, self.response_inst_mock = self.patchClass(
            server.pr, 'Response')

        # other mocking
        self.proxy_inst_mock.is_running = True
        self.executor_mock = mock.MagicMock(name='executor')
        self.message_mock = mock.MagicMock(name='message')
        self.message_mock.properties = {'correlation_id': self.task_uuid,
                                        'reply_to': self.reply_to,
                                        'type': pr.REQUEST}
        self.master_mock.attach_mock(self.executor_mock, 'executor')
        self.master_mock.attach_mock(self.message_mock, 'message')

    def server(self, reset_master_mock=False, **kwargs):
        server_kwargs = dict(topic=self.server_topic,
                             exchange=self.server_exchange,
                             executor=self.executor_mock,
                             endpoints=self.endpoints,
                             url=self.broker_url)
        server_kwargs.update(kwargs)
        s = server.Server(**server_kwargs)
        if reset_master_mock:
            self.resetMasterMock()
        return s

    def make_request(self, **kwargs):
        request_kwargs = dict(task=self.task,
                              uuid=self.task_uuid,
                              action=self.task_action,
                              arguments=self.task_args,
                              progress_callback=None,
                              timeout=60)
        request_kwargs.update(kwargs)
        return pr.Request(**request_kwargs).to_dict()

    def test_creation(self):
        s = self.server()

        # check calls
        master_mock_calls = [
            mock.call.Proxy(self.server_topic, self.server_exchange,
                            mock.ANY, url=self.broker_url, on_wait=mock.ANY)
        ]
        self.master_mock.assert_has_calls(master_mock_calls)
        self.assertEqual(len(s._endpoints), 3)

    def test_creation_with_endpoints(self):
        s = self.server(endpoints=self.endpoints)

        # check calls
        master_mock_calls = [
            mock.call.Proxy(self.server_topic, self.server_exchange,
                            mock.ANY, url=self.broker_url, on_wait=mock.ANY)
        ]
        self.master_mock.assert_has_calls(master_mock_calls)
        self.assertEqual(len(s._endpoints), len(self.endpoints))

    def test_parse_request(self):
        request = self.make_request()
        task_cls, action, task_args = server.Server._parse_request(**request)

        self.assertEqual((task_cls, action, task_args),
                         (self.task.name, self.task_action,
                          dict(task_name=self.task.name,
                               arguments=self.task_args)))

    def test_parse_request_with_success_result(self):
        request = self.make_request(action='revert', result=1)
        task_cls, action, task_args = server.Server._parse_request(**request)

        self.assertEqual((task_cls, action, task_args),
                         (self.task.name, 'revert',
                          dict(task_name=self.task.name,
                               arguments=self.task_args,
                               result=1)))

    def test_parse_request_with_failure_result(self):
        a_failure = failure.Failure.from_exception(Exception('test'))
        request = self.make_request(action='revert', result=a_failure)
        task_cls, action, task_args = server.Server._parse_request(**request)

        self.assertEqual((task_cls, action, task_args),
                         (self.task.name, 'revert',
                          dict(task_name=self.task.name,
                               arguments=self.task_args,
                               result=utils.FailureMatcher(a_failure))))

    def test_parse_request_with_failures(self):
        failures = {'0': failure.Failure.from_exception(Exception('test1')),
                    '1': failure.Failure.from_exception(Exception('test2'))}
        request = self.make_request(action='revert', failures=failures)
        task_cls, action, task_args = server.Server._parse_request(**request)

        self.assertEqual(
            (task_cls, action, task_args),
            (self.task.name, 'revert',
             dict(task_name=self.task.name,
                  arguments=self.task_args,
                  failures=dict((i, utils.FailureMatcher(f))
                                for i, f in six.iteritems(failures)))))

    @mock.patch("taskflow.engines.worker_based.server.LOG.critical")
    def test_reply_publish_failure(self, mocked_exception):
        self.proxy_inst_mock.publish.side_effect = RuntimeError('Woot!')

        # create server and process request
        s = self.server(reset_master_mock=True)
        s._reply(True, self.reply_to, self.task_uuid)

        self.assertEqual(self.master_mock.mock_calls, [
            mock.call.Response(pr.FAILURE),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid)
        ])
        self.assertTrue(mocked_exception.called)

    def test_on_run_reply_failure(self):
        request = self.make_request(task=utils.ProgressingTask(), arguments={})
        self.proxy_inst_mock.publish.side_effect = RuntimeError('Woot!')

        # create server and process request
        s = self.server(reset_master_mock=True)
        s._process_request(request, self.message_mock)

        self.assertEqual(1, self.proxy_inst_mock.publish.call_count)

    def test_on_update_progress(self):
        request = self.make_request(task=utils.ProgressingTask(), arguments={})

        # create server and process request
        s = self.server(reset_master_mock=True)
        s._process_request(request, self.message_mock)

        # check calls
        master_mock_calls = [
            mock.call.Response(pr.RUNNING),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid),
            mock.call.Response(pr.PROGRESS, progress=0.0, event_data={}),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid),
            mock.call.Response(pr.PROGRESS, progress=1.0, event_data={}),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid),
            mock.call.Response(pr.SUCCESS, result=5),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_process_request(self):
        # create server and process request
        s = self.server(reset_master_mock=True)
        s._process_request(self.make_request(), self.message_mock)

        # check calls
        master_mock_calls = [
            mock.call.Response(pr.RUNNING),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid),
            mock.call.Response(pr.SUCCESS, result=1),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    @mock.patch("taskflow.engines.worker_based.server.LOG.warn")
    def test_process_request_parse_message_failure(self, mocked_exception):
        self.message_mock.properties = {}
        request = self.make_request()
        s = self.server(reset_master_mock=True)
        s._process_request(request, self.message_mock)

        self.assertEqual(self.master_mock.mock_calls, [])
        self.assertTrue(mocked_exception.called)

    @mock.patch.object(failure.Failure, 'from_dict')
    @mock.patch.object(failure.Failure, 'to_dict')
    def test_process_request_parse_request_failure(self, to_mock, from_mock):
        failure_dict = {
            'failure': 'failure',
        }
        a_failure = failure.Failure.from_exception(RuntimeError('Woot!'))
        to_mock.return_value = failure_dict
        from_mock.side_effect = ValueError('Woot!')
        request = self.make_request(result=a_failure)

        # create server and process request
        s = self.server(reset_master_mock=True)
        s._process_request(request, self.message_mock)

        # check calls
        master_mock_calls = [
            mock.call.Response(pr.FAILURE, result=failure_dict),
            mock.call.proxy.publish(self.response_inst_mock,
                                    self.reply_to,
                                    correlation_id=self.task_uuid)
        ]
        self.assertEqual(master_mock_calls, self.master_mock.mock_calls)

    @mock.patch.object(failure.Failure, 'to_dict')
    def test_process_request_endpoint_not_found(self, to_mock):
        failure_dict = {
            'failure': 'failure',
        }
        to_mock.return_value = failure_dict
        request = self.make_request(task=mock.MagicMock(name='<unknown>'))

        # create server and process request
        s = self.server(reset_master_mock=True)
        s._process_request(request, self.message_mock)

        # check calls
        master_mock_calls = [
            mock.call.Response(pr.FAILURE, result=failure_dict),
            mock.call.proxy.publish(self.response_inst_mock,
                                    self.reply_to,
                                    correlation_id=self.task_uuid)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    @mock.patch.object(failure.Failure, 'to_dict')
    def test_process_request_execution_failure(self, to_mock):
        failure_dict = {
            'failure': 'failure',
        }
        to_mock.return_value = failure_dict
        request = self.make_request()
        request['action'] = '<unknown>'

        # create server and process request
        s = self.server(reset_master_mock=True)
        s._process_request(request, self.message_mock)

        # check calls
        master_mock_calls = [
            mock.call.Response(pr.FAILURE, result=failure_dict),
            mock.call.proxy.publish(self.response_inst_mock,
                                    self.reply_to,
                                    correlation_id=self.task_uuid)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    @mock.patch.object(failure.Failure, 'to_dict')
    def test_process_request_task_failure(self, to_mock):
        failure_dict = {
            'failure': 'failure',
        }
        to_mock.return_value = failure_dict
        request = self.make_request(task=utils.TaskWithFailure(), arguments={})

        # create server and process request
        s = self.server(reset_master_mock=True)
        s._process_request(request, self.message_mock)

        # check calls
        master_mock_calls = [
            mock.call.Response(pr.RUNNING),
            mock.call.proxy.publish(self.response_inst_mock, self.reply_to,
                                    correlation_id=self.task_uuid),
            mock.call.Response(pr.FAILURE, result=failure_dict),
            mock.call.proxy.publish(self.response_inst_mock,
                                    self.reply_to,
                                    correlation_id=self.task_uuid)
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_start(self):
        self.server(reset_master_mock=True).start()

        # check calls
        master_mock_calls = [
            mock.call.proxy.start()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_wait(self):
        server = self.server(reset_master_mock=True)
        server.start()
        server.wait()

        # check calls
        master_mock_calls = [
            mock.call.proxy.start(),
            mock.call.proxy.wait()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)

    def test_stop(self):
        self.server(reset_master_mock=True).stop()

        # check calls
        master_mock_calls = [
            mock.call.proxy.stop()
        ]
        self.assertEqual(self.master_mock.mock_calls, master_mock_calls)
