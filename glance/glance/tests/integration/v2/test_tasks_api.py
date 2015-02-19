# Copyright 2013 Rackspace Hosting
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

from glance.api.v2 import tasks
import glance.openstack.common.jsonutils as json
from glance.tests.integration.v2 import base

TENANT1 = '6838eb7b-6ded-434a-882c-b344c77fe8df'
TENANT2 = '2c014f32-55eb-467d-8fcb-4bd706012f81'
TENANT3 = '5a3e60e8-cfa9-4a9e-a90a-62b42cea92b8'
TENANT4 = 'c6c87f25-8a94-47ed-8c83-053c25f42df4'


def minimal_task_headers(owner='tenant1'):
    headers = {
        'X-Auth-Token': 'user1:%s:admin' % owner,
        'Content-Type': 'application/json',
    }
    return headers


def _new_task_fixture(**kwargs):
    task_data = {
        "type": "import",
        "input": {
            "import_from": "/some/file/path",
            "import_from_format": "qcow2",
            "image_properties": {
                'disk_format': 'vhd',
                'container_format': 'ovf'
            }
        }
    }
    task_data.update(kwargs)
    return task_data


class TestTasksApi(base.ApiTest):

    def __init__(self, *args, **kwargs):
        super(TestTasksApi, self).__init__(*args, **kwargs)
        self.api_flavor = 'fakeauth'
        self.registry_flavor = 'fakeauth'

    def _post_new_task(self, **kwargs):
        task_owner = kwargs['owner']
        headers = minimal_task_headers(task_owner)
        task_data = _new_task_fixture()
        body_content = json.dumps(task_data)

        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=headers,
                                              body=body_content)

        self.assertEqual(response.status, 201)

        task = json.loads(content)
        return task

    def test_all_task_api(self):
        # 0. GET /tasks
        # Verify no tasks
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        content_dict = json.loads(content)

        self.assertEqual(response.status, 200)
        self.assertFalse(content_dict['tasks'])

        # 1. GET /tasks/{task_id}
        # Verify non-existent task
        task_id = 'NON_EXISTENT_TASK'
        path = "/v2/tasks/%s" % task_id
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 404)

        # 2. POST /tasks
        # Create a new task
        task_data = _new_task_fixture()
        task_owner = 'tenant1'
        body_content = json.dumps(task_data)

        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=
                                              minimal_task_headers(task_owner),
                                              body=body_content)
        self.assertEqual(response.status, 201)

        data = json.loads(content)
        task_id = data['id']

        self.assertIsNotNone(task_id)
        self.assertEqual(task_owner, data['owner'])
        self.assertEqual(task_data['type'], data['type'])
        self.assertEqual(task_data['input'], data['input'])

        # 3. GET /tasks/{task_id}
        # Get an existing task
        path = "/v2/tasks/%s" % task_id
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)

        # 4. GET /tasks/{task_id}
        # Get all tasks (not deleted)
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)
        self.assertIsNotNone(content)

        data = json.loads(content)
        self.assertIsNotNone(data)
        self.assertEqual(1, len(data['tasks']))
        #NOTE(venkatesh) find a way to get expected_keys from tasks controller
        expected_keys = set(['id', 'type', 'owner', 'status',
                             'created_at', 'updated_at', 'self', 'schema'])
        task = data['tasks'][0]
        self.assertEqual(expected_keys, set(task.keys()))
        self.assertEqual(task_data['type'], task['type'])
        self.assertEqual(task_owner, task['owner'])
        self.assertEqual('pending', task['status'])
        self.assertIsNotNone(task['created_at'])
        self.assertIsNotNone(task['updated_at'])

    def test_task_schema_api(self):
        # 0. GET /schemas/task
        # Verify schema for task
        path = "/v2/schemas/task"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)

        schema = tasks.get_task_schema()
        expected_schema = schema.minimal()
        data = json.loads(content)
        self.assertIsNotNone(data)
        self.assertEqual(expected_schema, data)

        # 1. GET /schemas/tasks
        # Verify schema for tasks
        path = "/v2/schemas/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)

        schema = tasks.get_collection_schema()
        expected_schema = schema.minimal()
        data = json.loads(content)
        self.assertIsNotNone(data)
        self.assertEqual(expected_schema, data)

    def test_create_new_task(self):
        # 0. POST /tasks
        # Create a new task with valid input and type
        task_data = _new_task_fixture()
        task_owner = 'tenant1'
        body_content = json.dumps(task_data)

        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=
                                              minimal_task_headers(task_owner),
                                              body=body_content)
        self.assertEqual(response.status, 201)

        data = json.loads(content)
        task_id = data['id']

        self.assertIsNotNone(task_id)
        self.assertEqual(task_owner, data['owner'])
        self.assertEqual(task_data['type'], data['type'])
        self.assertEqual(task_data['input'], data['input'])

        # 1. POST /tasks
        # Create a new task with invalid type
        # Expect BadRequest(400) Error as response
        task_data = _new_task_fixture(type='invalid')
        task_owner = 'tenant1'
        body_content = json.dumps(task_data)

        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=
                                              minimal_task_headers(task_owner),
                                              body=body_content)
        self.assertEqual(response.status, 400)

        # 1. POST /tasks
        # Create a new task with invalid input for type 'import'
        # Expect BadRequest(400) Error as response
        task_data = _new_task_fixture(input='{something: invalid}')
        task_owner = 'tenant1'
        body_content = json.dumps(task_data)

        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=
                                              minimal_task_headers(task_owner),
                                              body=body_content)
        self.assertEqual(response.status, 400)

    def test_tasks_with_filter(self):

        # 0. GET /v2/tasks
        # Verify no tasks
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        content_dict = json.loads(content)
        self.assertFalse(content_dict['tasks'])

        task_ids = []

        # 1. POST /tasks with two tasks with status 'pending' and 'processing'
        # with various attributes
        task_owner = TENANT1
        headers = minimal_task_headers(task_owner)
        task_data = _new_task_fixture()
        body_content = json.dumps(task_data)
        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=headers,
                                              body=body_content)
        self.assertEqual(response.status, 201)
        data = json.loads(content)
        task_ids.append(data['id'])

        task_owner = TENANT2
        headers = minimal_task_headers(task_owner)
        task_data = _new_task_fixture()
        body_content = json.dumps(task_data)
        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=headers,
                                              body=body_content)
        self.assertEqual(response.status, 201)
        data = json.loads(content)
        task_ids.append(data['id'])

        # 2. GET /tasks
        # Verify two import tasks
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        content_dict = json.loads(content)
        self.assertEqual(2, len(content_dict['tasks']))

        # 3. GET /tasks with owner filter
        # Verify correct task returned with owner
        params = "owner=%s" % TENANT1
        path = "/v2/tasks?%s" % params

        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        content_dict = json.loads(content)
        self.assertEqual(1, len(content_dict['tasks']))
        self.assertEqual(TENANT1, content_dict['tasks'][0]['owner'])

        # Check the same for different owner.
        params = "owner=%s" % TENANT2
        path = "/v2/tasks?%s" % params

        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        content_dict = json.loads(content)
        self.assertEqual(1, len(content_dict['tasks']))
        self.assertEqual(TENANT2, content_dict['tasks'][0]['owner'])

        # 4. GET /tasks with type filter
        # Verify correct task returned with type
        params = "type=import"
        path = "/v2/tasks?%s" % params

        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)

        content_dict = json.loads(content)
        self.assertEqual(2, len(content_dict['tasks']))

        actual_task_ids = [task['id'] for task in content_dict['tasks']]
        self.assertEqual(set(task_ids), set(actual_task_ids))

        # 5. GET /tasks with status filter
        # Verify correct tasks are returned for status 'pending'
        params = "status=pending"
        path = "/v2/tasks?%s" % params

        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)

        content_dict = json.loads(content)
        self.assertEqual(2, len(content_dict['tasks']))

        actual_task_ids = [task['id'] for task in content_dict['tasks']]
        self.assertEqual(set(task_ids), set(actual_task_ids))

        # 6. GET /tasks with status filter
        # Verify no task are returned for status which is not 'pending'
        params = "status=success"
        path = "/v2/tasks?%s" % params

        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)

        content_dict = json.loads(content)
        self.assertEqual(0, len(content_dict['tasks']))

    def test_limited_tasks(self):
        """
        Ensure marker and limit query params work
        """

        # 0. GET /tasks
        # Verify no tasks
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)
        tasks = json.loads(content)
        self.assertFalse(tasks['tasks'])

        task_ids = []

        # 1. POST /tasks with three tasks with various attributes

        task = self._post_new_task(owner=TENANT1)
        task_ids.append(task['id'])

        task = self._post_new_task(owner=TENANT2)
        task_ids.append(task['id'])

        task = self._post_new_task(owner=TENANT3)
        task_ids.append(task['id'])

        # 2. GET /tasks
        # Verify 3 tasks are returned
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        tasks = json.loads(content)['tasks']

        self.assertEqual(3, len(tasks))

        # 3. GET /tasks with limit of 2
        # Verify only two tasks were returned
        params = "limit=2"
        path = "/v2/tasks?%s" % params
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        actual_tasks = json.loads(content)['tasks']

        self.assertEqual(2, len(actual_tasks))
        self.assertEqual(tasks[0]['id'], actual_tasks[0]['id'])
        self.assertEqual(tasks[1]['id'], actual_tasks[1]['id'])

        # 4. GET /tasks with marker
        # Verify only two tasks were returned
        params = "marker=%s" % tasks[0]['id']
        path = "/v2/tasks?%s" % params
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        actual_tasks = json.loads(content)['tasks']

        self.assertEqual(2, len(actual_tasks))
        self.assertEqual(tasks[1]['id'], actual_tasks[0]['id'])
        self.assertEqual(tasks[2]['id'], actual_tasks[1]['id'])

        # 5. GET /tasks with marker and limit
        # Verify only one task was returned with the correct id
        params = "limit=1&marker=%s" % tasks[1]['id']
        path = "/v2/tasks?%s" % params
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        actual_tasks = json.loads(content)['tasks']

        self.assertEqual(1, len(actual_tasks))
        self.assertEqual(tasks[2]['id'], actual_tasks[0]['id'])

    def test_ordered_tasks(self):
        # 0. GET /tasks
        # Verify no tasks
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)
        tasks = json.loads(content)
        self.assertFalse(tasks['tasks'])

        task_ids = []

        # 1. POST /tasks with three tasks with various attributes
        task = self._post_new_task(owner=TENANT1)
        task_ids.append(task['id'])

        task = self._post_new_task(owner=TENANT2)
        task_ids.append(task['id'])

        task = self._post_new_task(owner=TENANT3)
        task_ids.append(task['id'])

        # 2. GET /tasks with no query params
        # Verify three tasks sorted by created_at desc
        # 2. GET /tasks
        # Verify 3 tasks are returned
        path = "/v2/tasks"
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        actual_tasks = json.loads(content)['tasks']

        self.assertEqual(3, len(actual_tasks))
        self.assertEqual(task_ids[2], actual_tasks[0]['id'])
        self.assertEqual(task_ids[1], actual_tasks[1]['id'])
        self.assertEqual(task_ids[0], actual_tasks[2]['id'])

        # 3. GET /tasks sorted by owner asc
        params = 'sort_key=owner&sort_dir=asc'
        path = '/v2/tasks?%s' % params
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        expected_task_owners = [TENANT1, TENANT2, TENANT3]
        expected_task_owners.sort()

        actual_tasks = json.loads(content)['tasks']
        self.assertEqual(3, len(actual_tasks))
        self.assertEqual(expected_task_owners,
                         [t['owner'] for t in actual_tasks])

        # 4. GET /tasks sorted by owner desc with a marker
        params = 'sort_key=owner&sort_dir=desc&marker=%s' % task_ids[0]
        path = '/v2/tasks?%s' % params
        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        actual_tasks = json.loads(content)['tasks']
        self.assertEqual(2, len(actual_tasks))
        self.assertEqual(task_ids[2], actual_tasks[0]['id'])
        self.assertEqual(task_ids[1], actual_tasks[1]['id'])
        self.assertEqual(TENANT3, actual_tasks[0]['owner'])
        self.assertEqual(TENANT2, actual_tasks[1]['owner'])

        # 5. GET /tasks sorted by owner asc with a marker
        params = 'sort_key=owner&sort_dir=asc&marker=%s' % task_ids[0]
        path = '/v2/tasks?%s' % params

        response, content = self.http.request(path, 'GET',
                                              headers=minimal_task_headers())

        self.assertEqual(response.status, 200)

        actual_tasks = json.loads(content)['tasks']

        self.assertEqual(0, len(actual_tasks))

    def test_delete_task(self):
        # 0. POST /tasks
        # Create a new task with valid input and type
        task_data = _new_task_fixture()
        task_owner = 'tenant1'
        body_content = json.dumps(task_data)

        path = "/v2/tasks"
        response, content = self.http.request(path, 'POST',
                                              headers=
                                              minimal_task_headers(task_owner),
                                              body=body_content)
        self.assertEqual(response.status, 201)

        data = json.loads(content)
        task_id = data['id']

        # 1. DELETE on /tasks/{task_id}
        # Attempt to delete a task
        path = "/v2/tasks/%s" % task_id
        response, content = self.http.request(path,
                                              'DELETE',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 405)
        self.assertEqual('GET', response.webob_resp.headers.get('Allow'))
        self.assertEqual(('GET',), response.webob_resp.allow)
        self.assertEqual(('GET',), response.allow)

        # 2. GET /tasks/{task_id}
        # Ensure that methods mentioned in the Allow header work
        path = "/v2/tasks/%s" % task_id
        response, content = self.http.request(path,
                                              'GET',
                                              headers=minimal_task_headers())
        self.assertEqual(response.status, 200)
        self.assertIsNotNone(content)
