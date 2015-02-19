# Copyright 2011 OpenStack Foundation
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
Fakes For Scheduler tests.
"""

from cinder.openstack.common import timeutils
from cinder.scheduler import filter_scheduler
from cinder.scheduler import host_manager


class FakeFilterScheduler(filter_scheduler.FilterScheduler):
    def __init__(self, *args, **kwargs):
        super(FakeFilterScheduler, self).__init__(*args, **kwargs)
        self.host_manager = host_manager.HostManager()


class FakeHostManager(host_manager.HostManager):
    def __init__(self):
        super(FakeHostManager, self).__init__()

        self.service_states = {
            'host1': {'total_capacity_gb': 1024,
                      'free_capacity_gb': 1024,
                      'allocated_capacity_gb': 0,
                      'reserved_percentage': 10,
                      'volume_backend_name': 'lvm1',
                      'timestamp': None},
            'host2': {'total_capacity_gb': 2048,
                      'free_capacity_gb': 300,
                      'allocated_capacity_gb': 1748,
                      'reserved_percentage': 10,
                      'volume_backend_name': 'lvm2',
                      'timestamp': None},
            'host3': {'total_capacity_gb': 512,
                      'free_capacity_gb': 256,
                      'allocated_capacity_gb': 256,
                      'reserved_percentage': 0,
                      'volume_backend_name': 'lvm3',
                      'timestamp': None},
            'host4': {'total_capacity_gb': 2048,
                      'free_capacity_gb': 200,
                      'allocated_capacity_gb': 1848,
                      'reserved_percentage': 5,
                      'volume_backend_name': 'lvm4',
                      'timestamp': None},
        }


class FakeHostState(host_manager.HostState):
    def __init__(self, host, attribute_dict):
        super(FakeHostState, self).__init__(host)
        for (key, val) in attribute_dict.iteritems():
            setattr(self, key, val)


def mock_host_manager_db_calls(mock_obj):
    services = [
        dict(id=1, host='host1', topic='volume', disabled=False,
             availability_zone='zone1', updated_at=timeutils.utcnow()),
        dict(id=2, host='host2', topic='volume', disabled=False,
             availability_zone='zone1', updated_at=timeutils.utcnow()),
        dict(id=3, host='host3', topic='volume', disabled=False,
             availability_zone='zone2', updated_at=timeutils.utcnow()),
        dict(id=4, host='host4', topic='volume', disabled=False,
             availability_zone='zone3', updated_at=timeutils.utcnow()),
        # service on host5 is disabled
        dict(id=5, host='host5', topic='volume', disabled=True,
             availability_zone='zone4', updated_at=timeutils.utcnow()),
    ]
    mock_obj.return_value = services
