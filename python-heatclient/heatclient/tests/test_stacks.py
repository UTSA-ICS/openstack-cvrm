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
from heatclient.v1.stacks import Stack
from heatclient.v1.stacks import StackManager

from mock import MagicMock
import testscenarios
from testscenarios.scenarios import multiply_scenarios
import testtools

load_tests = testscenarios.load_tests_apply_scenarios


def mock_stack(manager, stack_name, stack_id):
    return Stack(manager, {
        "id": stack_id,
        "stack_name": stack_name,
        "links": [{
            "href": "http://192.0.2.1:8004/v1/1234/stacks/%s/%s" % (
                stack_name, stack_id),
            "rel": "self"}],
        "description": "No description",
        "stack_status_reason": "Stack create completed successfully",
        "creation_time": "2013-08-04T20:57:55Z",
        "updated_time": "2013-08-04T20:57:55Z",
        "stack_status": "CREATE_COMPLETE"
    })


class StackStatusActionTest(testtools.TestCase):

    scenarios = multiply_scenarios([
        ('CREATE', dict(action='CREATE')),
        ('DELETE', dict(action='DELETE')),
        ('UPDATE', dict(action='UPDATE')),
        ('ROLLBACK', dict(action='ROLLBACK')),
        ('SUSPEND', dict(action='SUSPEND')),
        ('RESUME', dict(action='RESUME')),
        ('CHECK', dict(action='CHECK'))
    ], [
        ('IN_PROGRESS', dict(status='IN_PROGRESS')),
        ('FAILED', dict(status='FAILED')),
        ('COMPLETE', dict(status='COMPLETE'))
    ])

    def test_status_action(self):
        stack_status = '%s_%s' % (self.action, self.status)
        stack = mock_stack(None, 'stack_1', 'abcd1234')
        stack.stack_status = stack_status
        self.assertEqual(self.action, stack.action)
        self.assertEqual(self.status, stack.status)


class StackIdentifierTest(testtools.TestCase):

    def test_stack_identifier(self):
        stack = mock_stack(None, 'the_stack', 'abcd1234')
        self.assertEqual('the_stack/abcd1234', stack.identifier)


class StackOperationsTest(testtools.TestCase):

    def test_delete_stack(self):
        manager = MagicMock()
        stack = mock_stack(manager, 'the_stack', 'abcd1234')
        stack.delete()
        manager.delete.assert_called_once_with('the_stack/abcd1234')

    def test_abandon_stack(self):
        manager = MagicMock()
        stack = mock_stack(manager, 'the_stack', 'abcd1234')
        stack.abandon()
        manager.abandon.assert_called_once_with('the_stack/abcd1234')

    def test_get_stack(self):
        manager = MagicMock()
        stack = mock_stack(manager, 'the_stack', 'abcd1234')
        stack.get()
        manager.get.assert_called_once_with('the_stack/abcd1234')

    def test_update_stack(self):
        manager = MagicMock()
        stack = mock_stack(manager, 'the_stack', 'abcd1234')
        stack.update()
        manager.update.assert_called_once_with('the_stack/abcd1234')

    def test_create_stack(self):
        manager = MagicMock()
        stack = mock_stack(manager, 'the_stack', 'abcd1234')
        stack = stack.create()
        manager.create.assert_called_once_with('the_stack/abcd1234')

    def test_preview_stack(self):
        manager = MagicMock()
        stack = mock_stack(manager, 'the_stack', 'abcd1234')
        stack = stack.preview()
        manager.preview.assert_called_once_with()


class StackManagerNoPaginationTest(testtools.TestCase):

    scenarios = [
        ('total_0', dict(total=0)),
        ('total_1', dict(total=1)),
        ('total_9', dict(total=9)),
        ('total_10', dict(total=10)),
        ('total_11', dict(total=11)),
        ('total_19', dict(total=19)),
        ('total_20', dict(total=20)),
        ('total_21', dict(total=21)),
        ('total_49', dict(total=49)),
        ('total_50', dict(total=50)),
        ('total_51', dict(total=51)),
        ('total_95', dict(total=95)),
    ]

    # absolute limit for results returned
    limit = 50

    def mock_manager(self):
        manager = StackManager(None)
        manager._list = MagicMock()

        def mock_list(*args, **kwargs):
            def results():
                for i in range(0, self.total):
                    stack_name = 'stack_%s' % (i + 1)
                    stack_id = 'abcd1234-%s' % (i + 1)
                    yield mock_stack(manager, stack_name, stack_id)

            return list(results())

        manager._list.side_effect = mock_list
        return manager

    def test_stack_list_no_pagination(self):
        manager = self.mock_manager()

        results = list(manager.list())
        manager._list.assert_called_once_with(
            '/stacks?', 'stacks')

        # paginate is not specified, so the total
        # results is always returned
        self.assertEqual(self.total, len(results))

        if self.total > 0:
            self.assertEqual('stack_1', results[0].stack_name)
            self.assertEqual('stack_%s' % self.total, results[-1].stack_name)


class StackManagerPaginationTest(testtools.TestCase):

    scenarios = [
        ('0_offset_0', dict(
            offset=0,
            total=0,
            results=((0, 0),)
        )),
        ('1_offset_0', dict(
            offset=0,
            total=1,
            results=((0, 1),)
        )),
        ('9_offset_0', dict(
            offset=0,
            total=9,
            results=((0, 9),)
        )),
        ('10_offset_0', dict(
            offset=0,
            total=10,
            results=((0, 10), (10, 10))
        )),
        ('11_offset_0', dict(
            offset=0,
            total=11,
            results=((0, 10), (10, 11))
        )),
        ('11_offset_10', dict(
            offset=10,
            total=11,
            results=((10, 11),)
        )),
        ('19_offset_10', dict(
            offset=10,
            total=19,
            results=((10, 19),)
        )),
        ('20_offset_10', dict(
            offset=10,
            total=20,
            results=((10, 20), (20, 20))
        )),
        ('21_offset_10', dict(
            offset=10,
            total=21,
            results=((10, 20), (20, 21))
        )),
        ('21_offset_0', dict(
            offset=0,
            total=21,
            results=((0, 10), (10, 20), (20, 21))
        )),
        ('21_offset_20', dict(
            offset=20,
            total=21,
            results=((20, 21),)
        )),
        ('95_offset_90', dict(
            offset=90,
            total=95,
            results=((90, 95),)
        )),
    ]

    # absolute limit for results returned
    limit = 50

    def mock_manager(self):
        manager = StackManager(None)
        manager._list = MagicMock()

        def mock_list(arg_url, arg_response_key):
            try:
                result = self.results[self.result_index]
            except IndexError:
                return []
            self.result_index = self.result_index + 1

            limit_string = 'limit=%s' % self.limit
            self.assertIn(limit_string, arg_url)

            offset = result[0]
            if offset > 0:
                offset_string = 'marker=abcd1234-%s' % offset
                self.assertIn(offset_string, arg_url)

            def results():

                for i in range(*result):
                    self.limit -= 1
                    stack_name = 'stack_%s' % (i + 1)
                    stack_id = 'abcd1234-%s' % (i + 1)
                    yield mock_stack(manager, stack_name, stack_id)

            return list(results())

        manager._list.side_effect = mock_list
        return manager

    def test_stack_list_pagination(self):
        manager = self.mock_manager()

        list_params = {'limit': self.limit}

        if self.offset > 0:
            marker = 'abcd1234-%s' % self.offset
            list_params['marker'] = marker

        self.result_index = 0
        results = list(manager.list(**list_params))

        # assert that the list method has been called enough times
        self.assertEqual(len(self.results), self.result_index)

        last_result = min(self.limit, self.total - self.offset)
        # one or more list calls have been recomposed into a single list
        self.assertEqual(last_result, len(results))

        if last_result > 0:
            self.assertEqual('stack_%s' % (self.offset + 1),
                             results[0].stack_name)
            self.assertEqual('stack_%s' % (self.offset + last_result),
                             results[-1].stack_name)
