#    Copyright 2014 IBM Corp.
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

"""Unit tests for cinder.db.api."""


import datetime

from oslo.config import cfg

from cinder import context
from cinder import db
from cinder import exception
from cinder.openstack.common import uuidutils
from cinder.quota import ReservableResource
from cinder import test


CONF = cfg.CONF


def _quota_reserve(context, project_id):
    """Create sample Quota, QuotaUsage and Reservation objects.

    There is no method db.quota_usage_create(), so we have to use
    db.quota_reserve() for creating QuotaUsage objects.

    Returns reservations uuids.

    """
    def get_sync(resource, usage):
        def sync(elevated, project_id, session):
            return {resource: usage}
        return sync
    quotas = {}
    resources = {}
    deltas = {}
    for i, resource in enumerate(('volumes', 'gigabytes')):
        quotas[resource] = db.quota_create(context, project_id,
                                           resource, i + 1)
        resources[resource] = ReservableResource(resource,
                                                 '_sync_%s' % resource)
        deltas[resource] = i + 1
    return db.quota_reserve(
        context, resources, quotas, deltas,
        datetime.datetime.utcnow(), datetime.datetime.utcnow(),
        datetime.timedelta(days=1), project_id
    )


class ModelsObjectComparatorMixin(object):
    def _dict_from_object(self, obj, ignored_keys):
        if ignored_keys is None:
            ignored_keys = []
        return dict([(k, v) for k, v in obj.iteritems()
                    if k not in ignored_keys])

    def _assertEqualObjects(self, obj1, obj2, ignored_keys=None):
        obj1 = self._dict_from_object(obj1, ignored_keys)
        obj2 = self._dict_from_object(obj2, ignored_keys)

        self.assertEqual(
            len(obj1), len(obj2),
            "Keys mismatch: %s" % str(set(obj1.keys()) ^ set(obj2.keys())))
        for key, value in obj1.iteritems():
            self.assertEqual(value, obj2[key])

    def _assertEqualListsOfObjects(self, objs1, objs2, ignored_keys=None):
        obj_to_dict = lambda o: self._dict_from_object(o, ignored_keys)
        sort_key = lambda d: [d[k] for k in sorted(d)]
        conv_and_sort = lambda obj: sorted(map(obj_to_dict, obj), key=sort_key)

        self.assertEqual(conv_and_sort(objs1), conv_and_sort(objs2))

    def _assertEqualListsOfPrimitivesAsSets(self, primitives1, primitives2):
        self.assertEqual(len(primitives1), len(primitives2))
        for primitive in primitives1:
            self.assertIn(primitive, primitives2)

        for primitive in primitives2:
            self.assertIn(primitive, primitives1)


class BaseTest(test.TestCase, ModelsObjectComparatorMixin):
    def setUp(self):
        super(BaseTest, self).setUp()
        self.ctxt = context.get_admin_context()


class DBAPIServiceTestCase(BaseTest):

    """Unit tests for cinder.db.api.service_*."""

    def _get_base_values(self):
        return {
            'host': 'fake_host',
            'binary': 'fake_binary',
            'topic': 'fake_topic',
            'report_count': 3,
            'disabled': False
        }

    def _create_service(self, values):
        v = self._get_base_values()
        v.update(values)
        return db.service_create(self.ctxt, v)

    def test_service_create(self):
        service = self._create_service({})
        self.assertFalse(service['id'] is None)
        for key, value in self._get_base_values().iteritems():
            self.assertEqual(value, service[key])

    def test_service_destroy(self):
        service1 = self._create_service({})
        service2 = self._create_service({'host': 'fake_host2'})

        db.service_destroy(self.ctxt, service1['id'])
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, self.ctxt, service1['id'])
        self._assertEqualObjects(db.service_get(self.ctxt, service2['id']),
                                 service2)

    def test_service_update(self):
        service = self._create_service({})
        new_values = {
            'host': 'fake_host1',
            'binary': 'fake_binary1',
            'topic': 'fake_topic1',
            'report_count': 4,
            'disabled': True
        }
        db.service_update(self.ctxt, service['id'], new_values)
        updated_service = db.service_get(self.ctxt, service['id'])
        for key, value in new_values.iteritems():
            self.assertEqual(value, updated_service[key])

    def test_service_update_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_update, self.ctxt, 100500, {})

    def test_service_get(self):
        service1 = self._create_service({})
        service2 = self._create_service({'host': 'some_other_fake_host'})
        real_service1 = db.service_get(self.ctxt, service1['id'])
        self._assertEqualObjects(service1, real_service1)

    def test_service_get_not_found_exception(self):
        self.assertRaises(exception.ServiceNotFound,
                          db.service_get, self.ctxt, 100500)

    def test_service_get_by_host_and_topic(self):
        service1 = self._create_service({'host': 'host1', 'topic': 'topic1'})
        service2 = self._create_service({'host': 'host2', 'topic': 'topic2'})

        real_service1 = db.service_get_by_host_and_topic(self.ctxt,
                                                         host='host1',
                                                         topic='topic1')
        self._assertEqualObjects(service1, real_service1)

    def test_service_get_all(self):
        values = [
            {'host': 'host1', 'topic': 'topic1'},
            {'host': 'host2', 'topic': 'topic2'},
            {'disabled': True}
        ]
        services = [self._create_service(vals) for vals in values]
        disabled_services = [services[-1]]
        non_disabled_services = services[:-1]

        compares = [
            (services, db.service_get_all(self.ctxt)),
            (disabled_services, db.service_get_all(self.ctxt, True)),
            (non_disabled_services, db.service_get_all(self.ctxt, False))
        ]
        for comp in compares:
            self._assertEqualListsOfObjects(*comp)

    def test_service_get_all_by_topic(self):
        values = [
            {'host': 'host1', 'topic': 't1'},
            {'host': 'host2', 'topic': 't1'},
            {'disabled': True, 'topic': 't1'},
            {'host': 'host3', 'topic': 't2'}
        ]
        services = [self._create_service(vals) for vals in values]
        expected = services[:2]
        real = db.service_get_all_by_topic(self.ctxt, 't1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_all_by_host(self):
        values = [
            {'host': 'host1', 'topic': 't1'},
            {'host': 'host1', 'topic': 't1'},
            {'host': 'host2', 'topic': 't1'},
            {'host': 'host3', 'topic': 't2'}
        ]
        services = [self._create_service(vals) for vals in values]

        expected = services[:2]
        real = db.service_get_all_by_host(self.ctxt, 'host1')
        self._assertEqualListsOfObjects(expected, real)

    def test_service_get_by_args(self):
        values = [
            {'host': 'host1', 'binary': 'a'},
            {'host': 'host2', 'binary': 'b'}
        ]
        services = [self._create_service(vals) for vals in values]

        service1 = db.service_get_by_args(self.ctxt, 'host1', 'a')
        self._assertEqualObjects(services[0], service1)

        service2 = db.service_get_by_args(self.ctxt, 'host2', 'b')
        self._assertEqualObjects(services[1], service2)

    def test_service_get_by_args_not_found_exception(self):
        self.assertRaises(exception.HostBinaryNotFound,
                          db.service_get_by_args,
                          self.ctxt, 'non-exists-host', 'a')

    def test_service_get_all_volume_sorted(self):
        values = [
            ({'host': 'h1', 'binary': 'a', 'topic': CONF.volume_topic},
             100),
            ({'host': 'h2', 'binary': 'b', 'topic': CONF.volume_topic},
             200),
            ({'host': 'h3', 'binary': 'b', 'topic': CONF.volume_topic},
             300)]
        services = []
        for vals, size in values:
            services.append(self._create_service(vals))
            db.volume_create(self.ctxt, {'host': vals['host'], 'size': size})
        for service, size in db.service_get_all_volume_sorted(self.ctxt):
            self._assertEqualObjects(services.pop(0), service)
            self.assertEqual(values.pop(0)[1], size)


class DBAPIVolumeTestCase(BaseTest):

    """Unit tests for cinder.db.api.volume_*."""

    def test_volume_create(self):
        volume = db.volume_create(self.ctxt, {'host': 'host1'})
        self.assertTrue(uuidutils.is_uuid_like(volume['id']))
        self.assertEqual(volume.host, 'host1')

    def test_volume_allocate_iscsi_target_no_more_targets(self):
        self.assertRaises(exception.NoMoreTargets,
                          db.volume_allocate_iscsi_target,
                          self.ctxt, 42, 'host1')

    def test_volume_allocate_iscsi_target(self):
        host = 'host1'
        volume = db.volume_create(self.ctxt, {'host': host})
        db.iscsi_target_create_safe(self.ctxt, {'host': host,
                                                'target_num': 42})
        target_num = db.volume_allocate_iscsi_target(self.ctxt, volume['id'],
                                                     host)
        self.assertEqual(target_num, 42)

    def test_volume_attached_invalid_uuid(self):
        self.assertRaises(exception.InvalidUUID, db.volume_attached, self.ctxt,
                          42, 'invalid-uuid', None, '/tmp')

    def test_volume_attached_to_instance(self):
        volume = db.volume_create(self.ctxt, {'host': 'host1'})
        instance_uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        db.volume_attached(self.ctxt, volume['id'],
                           instance_uuid, None, '/tmp')
        volume = db.volume_get(self.ctxt, volume['id'])
        self.assertEqual(volume['status'], 'in-use')
        self.assertEqual(volume['mountpoint'], '/tmp')
        self.assertEqual(volume['attach_status'], 'attached')
        self.assertEqual(volume['instance_uuid'], instance_uuid)
        self.assertIsNone(volume['attached_host'])

    def test_volume_attached_to_host(self):
        volume = db.volume_create(self.ctxt, {'host': 'host1'})
        host_name = 'fake_host'
        db.volume_attached(self.ctxt, volume['id'],
                           None, host_name, '/tmp')
        volume = db.volume_get(self.ctxt, volume['id'])
        self.assertEqual(volume['status'], 'in-use')
        self.assertEqual(volume['mountpoint'], '/tmp')
        self.assertEqual(volume['attach_status'], 'attached')
        self.assertIsNone(volume['instance_uuid'])
        self.assertEqual(volume['attached_host'], host_name)

    def test_volume_data_get_for_host(self):
        for i in xrange(3):
            for j in xrange(3):
                db.volume_create(self.ctxt, {'host': 'h%d' % i, 'size': 100})
        for i in xrange(3):
            self.assertEqual((3, 300),
                             db.volume_data_get_for_host(
                                 self.ctxt, 'h%d' % i))

    def test_volume_data_get_for_project(self):
        for i in xrange(3):
            for j in xrange(3):
                db.volume_create(self.ctxt, {'project_id': 'p%d' % i,
                                             'size': 100,
                                             'host': 'h-%d-%d' % (i, j),
                                             })
        for i in xrange(3):
            self.assertEqual((3, 300),
                             db.volume_data_get_for_project(
                                 self.ctxt, 'p%d' % i))

    def test_volume_detached_from_instance(self):
        volume = db.volume_create(self.ctxt, {})
        db.volume_attached(self.ctxt, volume['id'],
                           'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                           None, '/tmp')
        db.volume_detached(self.ctxt, volume['id'])
        volume = db.volume_get(self.ctxt, volume['id'])
        self.assertEqual('available', volume['status'])
        self.assertEqual('detached', volume['attach_status'])
        self.assertIsNone(volume['mountpoint'])
        self.assertIsNone(volume['instance_uuid'])
        self.assertIsNone(volume['attached_host'])

    def test_volume_detached_from_host(self):
        volume = db.volume_create(self.ctxt, {})
        db.volume_attached(self.ctxt, volume['id'],
                           None, 'fake_host', '/tmp')
        db.volume_detached(self.ctxt, volume['id'])
        volume = db.volume_get(self.ctxt, volume['id'])
        self.assertEqual('available', volume['status'])
        self.assertEqual('detached', volume['attach_status'])
        self.assertIsNone(volume['mountpoint'])
        self.assertIsNone(volume['instance_uuid'])
        self.assertIsNone(volume['attached_host'])

    def test_volume_get(self):
        volume = db.volume_create(self.ctxt, {})
        self._assertEqualObjects(volume, db.volume_get(self.ctxt,
                                                       volume['id']))

    def test_volume_destroy(self):
        volume = db.volume_create(self.ctxt, {})
        db.volume_destroy(self.ctxt, volume['id'])
        self.assertRaises(exception.VolumeNotFound, db.volume_get,
                          self.ctxt, volume['id'])

    def test_volume_get_all(self):
        volumes = [db.volume_create(self.ctxt,
                   {'host': 'h%d' % i, 'size': i})
                   for i in xrange(3)]
        self._assertEqualListsOfObjects(volumes, db.volume_get_all(
                                        self.ctxt, None, None, 'host', None))

    def test_volume_get_all_marker_passed(self):
        volumes = [
            db.volume_create(self.ctxt, {'id': 1}),
            db.volume_create(self.ctxt, {'id': 2}),
            db.volume_create(self.ctxt, {'id': 3}),
            db.volume_create(self.ctxt, {'id': 4}),
        ]

        self._assertEqualListsOfObjects(volumes[2:], db.volume_get_all(
                                        self.ctxt, 2, 2, 'id', None))

    def test_volume_get_all_by_host(self):
        volumes = []
        for i in xrange(3):
            volumes.append([db.volume_create(self.ctxt, {'host': 'h%d' % i})
                            for j in xrange(3)])
        for i in xrange(3):
            self._assertEqualListsOfObjects(volumes[i],
                                            db.volume_get_all_by_host(
                                            self.ctxt, 'h%d' % i))

    def test_volume_get_all_by_instance_uuid(self):
        instance_uuids = []
        volumes = []
        for i in xrange(3):
            instance_uuid = str(uuidutils.uuid.uuid1())
            instance_uuids.append(instance_uuid)
            volumes.append([db.volume_create(self.ctxt,
                            {'instance_uuid': instance_uuid})
                            for j in xrange(3)])
        for i in xrange(3):
            self._assertEqualListsOfObjects(volumes[i],
                                            db.volume_get_all_by_instance_uuid(
                                            self.ctxt, instance_uuids[i]))

    def test_volume_get_all_by_instance_uuid_empty(self):
        self.assertEqual([], db.volume_get_all_by_instance_uuid(self.ctxt,
                                                                'empty'))

    def test_volume_get_all_by_project(self):
        volumes = []
        for i in xrange(3):
            volumes.append([db.volume_create(self.ctxt, {
                'project_id': 'p%d' % i}) for j in xrange(3)])
        for i in xrange(3):
            self._assertEqualListsOfObjects(volumes[i],
                                            db.volume_get_all_by_project(
                                            self.ctxt, 'p%d' % i, None,
                                            None, 'host', None))

    def test_volume_get_by_name(self):
        db.volume_create(self.ctxt, {'display_name': 'vol1'})
        db.volume_create(self.ctxt, {'display_name': 'vol2'})
        db.volume_create(self.ctxt, {'display_name': 'vol3'})

        # no name filter
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc')
        self.assertEqual(len(volumes), 3)
        # filter on name
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc', {'display_name': 'vol2'})
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['display_name'], 'vol2')
        # filter no match
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc', {'display_name': 'vol4'})
        self.assertEqual(len(volumes), 0)

    def test_volume_list_by_status(self):
        db.volume_create(self.ctxt, {'display_name': 'vol1',
                                     'status': 'available'})
        db.volume_create(self.ctxt, {'display_name': 'vol2',
                                     'status': 'available'})
        db.volume_create(self.ctxt, {'display_name': 'vol3',
                                     'status': 'in-use'})

        # no status filter
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc')
        self.assertEqual(len(volumes), 3)
        # single match
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc', {'status': 'in-use'})
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['status'], 'in-use')
        # multiple match
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc', {'status': 'available'})
        self.assertEqual(len(volumes), 2)
        for volume in volumes:
            self.assertEqual(volume['status'], 'available')
        # multiple filters
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc', {'status': 'available',
                                            'display_name': 'vol1'})
        self.assertEqual(len(volumes), 1)
        self.assertEqual(volumes[0]['display_name'], 'vol1')
        self.assertEqual(volumes[0]['status'], 'available')
        # no match
        volumes = db.volume_get_all(self.ctxt, None, None, 'created_at',
                                    'asc', {'status': 'in-use',
                                            'display_name': 'vol1'})
        self.assertEqual(len(volumes), 0)

    def _assertEqualsVolumeOrderResult(self, correct_order, limit=None,
                                       sort_key='created_at', sort_dir='asc',
                                       filters=None, project_id=None,
                                       match_keys=['id', 'display_name',
                                                   'volume_metadata',
                                                   'created_at']):
        """"Verifies that volumes are returned in the correct order."""
        if project_id:
            result = db.volume_get_all_by_project(self.ctxt, project_id, None,
                                                  limit, sort_key,
                                                  sort_dir, filters=filters)
        else:
            result = db.volume_get_all(self.ctxt, None, limit, sort_key,
                                       sort_dir, filters=filters)
        self.assertEqual(len(correct_order), len(result))
        for vol1, vol2 in zip(result, correct_order):
            for key in match_keys:
                val1 = vol1.get(key)
                val2 = vol2.get(key)
                # metadata is a dict, compare the 'key' and 'value' of each
                if key == 'volume_metadata':
                    self.assertEqual(len(val1), len(val2))
                    val1_dict = dict((x.key, x.value) for x in val1)
                    val2_dict = dict((x.key, x.value) for x in val2)
                    self.assertDictMatch(val1_dict, val2_dict)
                else:
                    self.assertEqual(val1, val2)

    def test_volume_get_by_filter(self):
        """Verifies that all filtering is done at the DB layer."""
        vols = []
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g1',
                                       'display_name': 'name_%d' % i,
                                       'size': 1})
                     for i in xrange(2)])
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g1',
                                       'display_name': 'name_%d' % i,
                                       'size': 2})
                     for i in xrange(2)])
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g1',
                                       'display_name': 'name_%d' % i})
                     for i in xrange(2)])
        vols.extend([db.volume_create(self.ctxt,
                                      {'project_id': 'g2',
                                       'display_name': 'name_%d' % i,
                                       'size': 1})
                     for i in xrange(2)])

        # By project, filter on size and name
        filters = {'size': '1'}
        correct_order = [vols[0], vols[1]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            project_id='g1')
        filters = {'size': '1', 'display_name': 'name_1'}
        correct_order = [vols[1]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            project_id='g1')

        # Remove project scope
        filters = {'size': '1'}
        correct_order = [vols[0], vols[1], vols[6], vols[7]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters)
        filters = {'size': '1', 'display_name': 'name_1'}
        correct_order = [vols[1], vols[7]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters)

        # Remove size constraint
        filters = {'display_name': 'name_1'}
        correct_order = [vols[1], vols[3], vols[5]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters,
                                            project_id='g1')
        correct_order = [vols[1], vols[3], vols[5], vols[7]]
        self._assertEqualsVolumeOrderResult(correct_order, filters=filters)

        # Verify bogus values return nothing
        filters = {'display_name': 'name_1', 'bogus_value': 'foo'}
        self._assertEqualsVolumeOrderResult([], filters=filters,
                                            project_id='g1')
        self._assertEqualsVolumeOrderResult([], project_id='bogus')
        self._assertEqualsVolumeOrderResult([], filters=filters)
        self._assertEqualsVolumeOrderResult([], filters={'metadata':
                                                         'not valid'})
        self._assertEqualsVolumeOrderResult([], filters={'metadata':
                                                         ['not', 'valid']})

        # Verify that relationship property keys return nothing, these
        # exist on the Volumes model but are not columns
        filters = {'volume_type': 'bogus_type'}
        self._assertEqualsVolumeOrderResult([], filters=filters)

    def test_volume_get_all_filters_limit(self):
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1'})
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2'})
        vol3 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'metadata': {'key1': 'val1'}})
        vol4 = db.volume_create(self.ctxt, {'display_name': 'test3',
                                            'metadata': {'key1': 'val1',
                                                         'key2': 'val2'}})
        vol5 = db.volume_create(self.ctxt, {'display_name': 'test3',
                                            'metadata': {'key2': 'val2',
                                                         'key3': 'val3'},
                                            'host': 'host5'})
        vols = [vol1, vol2, vol3, vol4, vol5]

        # Ensure we have 5 total instances
        self._assertEqualsVolumeOrderResult(vols)

        # No filters, test limit
        self._assertEqualsVolumeOrderResult(vols[:1], limit=1)
        self._assertEqualsVolumeOrderResult(vols[:4], limit=4)

        # Just the test2 volumes
        filters = {'display_name': 'test2'}
        self._assertEqualsVolumeOrderResult([vol2, vol3], filters=filters)
        self._assertEqualsVolumeOrderResult([vol2], limit=1,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol2, vol3], limit=2,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol2, vol3], limit=100,
                                            filters=filters)

        # metdata filters
        filters = {'metadata': {'key1': 'val1'}}
        self._assertEqualsVolumeOrderResult([vol3, vol4], filters=filters)
        self._assertEqualsVolumeOrderResult([vol3], limit=1,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol3, vol4], limit=10,
                                            filters=filters)

        filters = {'metadata': {'key1': 'val1',
                                'key2': 'val2'}}
        self._assertEqualsVolumeOrderResult([vol4], filters=filters)
        self._assertEqualsVolumeOrderResult([vol4], limit=1,
                                            filters=filters)

        # No match
        filters = {'metadata': {'key1': 'val1',
                                'key2': 'val2',
                                'key3': 'val3'}}
        self._assertEqualsVolumeOrderResult([], filters=filters)
        filters = {'metadata': {'key1': 'val1',
                                'key2': 'bogus'}}
        self._assertEqualsVolumeOrderResult([], filters=filters)
        filters = {'metadata': {'key1': 'val1',
                                'key2': 'val1'}}
        self._assertEqualsVolumeOrderResult([], filters=filters)

        # Combination
        filters = {'display_name': 'test2',
                   'metadata': {'key1': 'val1'}}
        self._assertEqualsVolumeOrderResult([vol3], filters=filters)
        self._assertEqualsVolumeOrderResult([vol3], limit=1,
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol3], limit=100,
                                            filters=filters)
        filters = {'display_name': 'test3',
                   'metadata': {'key2': 'val2',
                                'key3': 'val3'},
                   'host': 'host5'}
        self._assertEqualsVolumeOrderResult([vol5], filters=filters)
        self._assertEqualsVolumeOrderResult([vol5], limit=1,
                                            filters=filters)

    def test_volume_get_no_migration_targets(self):
        """Verifies the unique 'no_migration_targets'=True filter.

        This filter returns volumes with either a NULL 'migration_status'
        or a non-NULL value that does not start with 'target:'.
        """
        vol1 = db.volume_create(self.ctxt, {'display_name': 'test1'})
        vol2 = db.volume_create(self.ctxt, {'display_name': 'test2',
                                            'migration_status': 'bogus'})
        vol3 = db.volume_create(self.ctxt, {'display_name': 'test3',
                                            'migration_status': 'btarget:'})
        vol4 = db.volume_create(self.ctxt, {'display_name': 'test4',
                                            'migration_status': 'target:'})
        vols = [vol1, vol2, vol3, vol4]

        # Ensure we have 4 total instances
        self._assertEqualsVolumeOrderResult(vols)

        # Apply the unique filter
        filters = {'no_migration_targets': True}
        self._assertEqualsVolumeOrderResult([vol1, vol2, vol3],
                                            filters=filters)
        self._assertEqualsVolumeOrderResult([vol1, vol2], limit=2,
                                            filters=filters)

        filters = {'no_migration_targets': True,
                   'display_name': 'test4'}
        self._assertEqualsVolumeOrderResult([], filters=filters)

    def test_volume_get_iscsi_target_num(self):
        target = db.iscsi_target_create_safe(self.ctxt, {'volume_id': 42,
                                                         'target_num': 43})
        self.assertEqual(43, db.volume_get_iscsi_target_num(self.ctxt, 42))

    def test_volume_get_iscsi_target_num_nonexistent(self):
        self.assertRaises(exception.ISCSITargetNotFoundForVolume,
                          db.volume_get_iscsi_target_num, self.ctxt, 42)

    def test_volume_update(self):
        volume = db.volume_create(self.ctxt, {'host': 'h1'})
        db.volume_update(self.ctxt, volume['id'],
                         {'host': 'h2', 'metadata': {'m1': 'v1'}})
        volume = db.volume_get(self.ctxt, volume['id'])
        self.assertEqual('h2', volume['host'])

    def test_volume_update_nonexistent(self):
        self.assertRaises(exception.VolumeNotFound, db.volume_update,
                          self.ctxt, 42, {})

    def test_volume_metadata_get(self):
        metadata = {'a': 'b', 'c': 'd'}
        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata})

        self.assertEqual(metadata, db.volume_metadata_get(self.ctxt, 1))

    def test_volume_metadata_update(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '5'}
        should_be = {'a': '3', 'c': '2', 'd': '5'}

        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata1})
        db_meta = db.volume_metadata_update(self.ctxt, 1, metadata2, False)

        self.assertEqual(should_be, db_meta)

    def test_volume_metadata_update_delete(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '4'}
        should_be = metadata2

        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata1})
        db_meta = db.volume_metadata_update(self.ctxt, 1, metadata2, True)

        self.assertEqual(should_be, db_meta)

    def test_volume_metadata_delete(self):
        metadata = {'a': 'b', 'c': 'd'}
        db.volume_create(self.ctxt, {'id': 1, 'metadata': metadata})
        db.volume_metadata_delete(self.ctxt, 1, 'c')
        metadata.pop('c')
        self.assertEqual(metadata, db.volume_metadata_get(self.ctxt, 1))


class DBAPISnapshotTestCase(BaseTest):

    """Tests for cinder.db.api.snapshot_*."""

    def test_snapshot_data_get_for_project(self):
        actual = db.snapshot_data_get_for_project(self.ctxt, 'project1')
        self.assertEqual(actual, (0, 0))
        db.volume_create(self.ctxt, {'id': 1,
                                     'project_id': 'project1',
                                     'size': 42})
        snapshot = db.snapshot_create(self.ctxt, {'id': 1, 'volume_id': 1,
                                                  'project_id': 'project1',
                                                  'volume_size': 42})
        actual = db.snapshot_data_get_for_project(self.ctxt, 'project1')
        self.assertEqual(actual, (1, 42))

    def test_snapshot_get_all(self):
        db.volume_create(self.ctxt, {'id': 1})
        snapshot = db.snapshot_create(self.ctxt, {'id': 1, 'volume_id': 1})
        self._assertEqualListsOfObjects([snapshot],
                                        db.snapshot_get_all(self.ctxt),
                                        ignored_keys=['metadata', 'volume'])

    def test_snapshot_metadata_get(self):
        metadata = {'a': 'b', 'c': 'd'}
        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata})

        self.assertEqual(metadata, db.snapshot_metadata_get(self.ctxt, 1))

    def test_snapshot_metadata_update(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '5'}
        should_be = {'a': '3', 'c': '2', 'd': '5'}

        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata1})
        db_meta = db.snapshot_metadata_update(self.ctxt, 1, metadata2, False)

        self.assertEqual(should_be, db_meta)

    def test_snapshot_metadata_update_delete(self):
        metadata1 = {'a': '1', 'c': '2'}
        metadata2 = {'a': '3', 'd': '5'}
        should_be = metadata2

        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata1})
        db_meta = db.snapshot_metadata_update(self.ctxt, 1, metadata2, True)

        self.assertEqual(should_be, db_meta)

    def test_snapshot_metadata_delete(self):
        metadata = {'a': '1', 'c': '2'}
        should_be = {'a': '1'}

        db.volume_create(self.ctxt, {'id': 1})
        db.snapshot_create(self.ctxt,
                           {'id': 1, 'volume_id': 1, 'metadata': metadata})
        db.snapshot_metadata_delete(self.ctxt, 1, 'c')

        self.assertEqual(should_be, db.snapshot_metadata_get(self.ctxt, 1))


class DBAPIVolumeTypeTestCase(BaseTest):

    """Tests for the db.api.volume_type_* methods."""

    def setUp(self):
        self.ctxt = context.get_admin_context()
        super(DBAPIVolumeTypeTestCase, self).setUp()

    def test_volume_type_create_exists(self):
        vt = db.volume_type_create(self.ctxt, {'name': 'n1'})
        self.assertRaises(exception.VolumeTypeExists,
                          db.volume_type_create,
                          self.ctxt,
                          {'name': 'n1'})
        self.assertRaises(exception.VolumeTypeExists,
                          db.volume_type_create,
                          self.ctxt,
                          {'name': 'n2', 'id': vt['id']})


class DBAPIEncryptionTestCase(BaseTest):

    """Tests for the db.api.volume_type_encryption_* methods."""

    _ignored_keys = [
        'deleted',
        'deleted_at',
        'created_at',
        'updated_at',
    ]

    def setUp(self):
        super(DBAPIEncryptionTestCase, self).setUp()
        self.created = \
            [db.volume_type_encryption_create(self.ctxt,
                                              values['volume_type_id'], values)
             for values in self._get_values()]

    def _get_values(self, one=False, updated=False):
        base_values = {
            'cipher': 'fake_cipher',
            'key_size': 256,
            'provider': 'fake_provider',
            'volume_type_id': 'fake_type',
            'control_location': 'front-end',
        }
        updated_values = {
            'cipher': 'fake_updated_cipher',
            'key_size': 512,
            'provider': 'fake_updated_provider',
            'volume_type_id': 'fake_type',
            'control_location': 'front-end',
        }

        if one:
            return base_values

        if updated:
            values = updated_values
        else:
            values = base_values

        def compose(val, step):
            if isinstance(val, str):
                step = str(step)
            return val + step

        return [dict([(k, compose(v, i)) for k, v in values.items()])
                for i in range(1, 4)]

    def test_volume_type_encryption_create(self):
        values = self._get_values()
        for i, encryption in enumerate(self.created):
            self._assertEqualObjects(values[i], encryption, self._ignored_keys)

    def test_volume_type_encryption_update(self):
        update_values = self._get_values(updated=True)
        self.updated = \
            [db.volume_type_encryption_update(self.ctxt,
                                              values['volume_type_id'], values)
             for values in update_values]
        for i, encryption in enumerate(self.updated):
            self._assertEqualObjects(update_values[i], encryption,
                                     self._ignored_keys)

    def test_volume_type_encryption_get(self):
        for encryption in self.created:
            encryption_get = \
                db.volume_type_encryption_get(self.ctxt,
                                              encryption['volume_type_id'])
            self._assertEqualObjects(encryption, encryption_get,
                                     self._ignored_keys)

    def test_volume_type_update_with_no_create(self):
        self.assertRaises(exception.VolumeTypeEncryptionNotFound,
                          db.volume_type_encryption_update,
                          self.ctxt,
                          'fake_no_create_type',
                          {'cipher': 'fake_updated_cipher'})

    def test_volume_type_encryption_delete(self):
        values = {
            'cipher': 'fake_cipher',
            'key_size': 256,
            'provider': 'fake_provider',
            'volume_type_id': 'fake_type',
            'control_location': 'front-end',
        }

        encryption = db.volume_type_encryption_create(self.ctxt, 'fake_type',
                                                      values)
        self._assertEqualObjects(values, encryption, self._ignored_keys)

        db.volume_type_encryption_delete(self.ctxt,
                                         encryption['volume_type_id'])
        encryption_get = \
            db.volume_type_encryption_get(self.ctxt,
                                          encryption['volume_type_id'])
        self.assertIsNone(encryption_get)


class DBAPIReservationTestCase(BaseTest):

    """Tests for db.api.reservation_* methods."""

    def setUp(self):
        super(DBAPIReservationTestCase, self).setUp()
        self.values = {
            'uuid': 'sample-uuid',
            'project_id': 'project1',
            'resource': 'resource',
            'delta': 42,
            'expire': (datetime.datetime.utcnow() +
                       datetime.timedelta(days=1)),
            'usage': {'id': 1}
        }

    def test_reservation_create(self):
        reservation = db.reservation_create(self.ctxt, **self.values)
        self._assertEqualObjects(self.values, reservation, ignored_keys=(
            'deleted', 'updated_at',
            'deleted_at', 'id',
            'created_at', 'usage',
            'usage_id'))
        self.assertEqual(reservation['usage_id'], self.values['usage']['id'])

    def test_reservation_get(self):
        reservation = db.reservation_create(self.ctxt, **self.values)
        reservation_db = db.reservation_get(self.ctxt, self.values['uuid'])
        self._assertEqualObjects(reservation, reservation_db)

    def test_reservation_get_nonexistent(self):
        self.assertRaises(exception.ReservationNotFound,
                          db.reservation_get,
                          self.ctxt,
                          'non-exitent-resevation-uuid')

    def test_reservation_commit(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 1, 'in_use': 0},
                    'gigabytes': {'reserved': 2, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt, 'project1'))
        db.reservation_get(self.ctxt, reservations[0])
        db.reservation_commit(self.ctxt, reservations, 'project1')
        self.assertRaises(exception.ReservationNotFound,
                          db.reservation_get,
                          self.ctxt,
                          reservations[0])
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 0, 'in_use': 1},
                    'gigabytes': {'reserved': 0, 'in_use': 2},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))

    def test_reservation_rollback(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 1, 'in_use': 0},
                    'gigabytes': {'reserved': 2, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))
        db.reservation_get(self.ctxt, reservations[0])
        db.reservation_rollback(self.ctxt, reservations, 'project1')
        self.assertRaises(exception.ReservationNotFound,
                          db.reservation_get,
                          self.ctxt,
                          reservations[0])
        expected = {'project_id': 'project1',
                    'volumes': {'reserved': 0, 'in_use': 0},
                    'gigabytes': {'reserved': 0, 'in_use': 0},
                    }
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))

    def test_reservation_get_all_by_project(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        r1 = db.reservation_get(self.ctxt, reservations[0])
        r2 = db.reservation_get(self.ctxt, reservations[1])
        expected = {'project_id': 'project1',
                    r1['resource']: {r1['uuid']: r1['delta']},
                    r2['resource']: {r2['uuid']: r2['delta']}}
        self.assertEqual(expected, db.reservation_get_all_by_project(
            self.ctxt, 'project1'))

    def test_reservation_expire(self):
        self.values['expire'] = datetime.datetime.utcnow() + \
            datetime.timedelta(days=1)
        reservations = _quota_reserve(self.ctxt, 'project1')
        db.reservation_expire(self.ctxt)

        expected = {'project_id': 'project1',
                    'gigabytes': {'reserved': 0, 'in_use': 0},
                    'volumes': {'reserved': 0, 'in_use': 0}}
        self.assertEqual(expected,
                         db.quota_usage_get_all_by_project(
                             self.ctxt,
                             'project1'))

    def test_reservation_destroy(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        r1 = db.reservation_get(self.ctxt, reservations[0])
        db.reservation_destroy(self.ctxt, reservations[1])
        expected = {'project_id': 'project1',
                    r1['resource']: {r1['uuid']: r1['delta']}}
        self.assertEqual(expected, db.reservation_get_all_by_project(
            self.ctxt, 'project1'))


class DBAPIQuotaClassTestCase(BaseTest):

    """Tests for db.api.quota_class_* methods."""

    def setUp(self):
        super(DBAPIQuotaClassTestCase, self).setUp()
        self.sample_qc = db.quota_class_create(self.ctxt, 'test_qc',
                                               'test_resource', 42)

    def test_quota_class_get(self):
        qc = db.quota_class_get(self.ctxt, 'test_qc', 'test_resource')
        self._assertEqualObjects(self.sample_qc, qc)

    def test_quota_class_destroy(self):
        db.quota_class_destroy(self.ctxt, 'test_qc', 'test_resource')
        self.assertRaises(exception.QuotaClassNotFound,
                          db.quota_class_get, self.ctxt,
                          'test_qc', 'test_resource')

    def test_quota_class_get_not_found(self):
        self.assertRaises(exception.QuotaClassNotFound,
                          db.quota_class_get, self.ctxt, 'nonexistent',
                          'nonexistent')

    def test_quota_class_get_all_by_name(self):
        sample1 = db.quota_class_create(self.ctxt, 'test2', 'res1', 43)
        sample2 = db.quota_class_create(self.ctxt, 'test2', 'res2', 44)
        self.assertEqual({'class_name': 'test_qc', 'test_resource': 42},
                         db.quota_class_get_all_by_name(self.ctxt, 'test_qc'))
        self.assertEqual({'class_name': 'test2', 'res1': 43, 'res2': 44},
                         db.quota_class_get_all_by_name(self.ctxt, 'test2'))

    def test_quota_class_update(self):
        db.quota_class_update(self.ctxt, 'test_qc', 'test_resource', 43)
        updated = db.quota_class_get(self.ctxt, 'test_qc', 'test_resource')
        self.assertEqual(43, updated['hard_limit'])

    def test_quota_class_destroy_all_by_name(self):
        sample1 = db.quota_class_create(self.ctxt, 'test2', 'res1', 43)
        sample2 = db.quota_class_create(self.ctxt, 'test2', 'res2', 44)
        db.quota_class_destroy_all_by_name(self.ctxt, 'test2')
        self.assertEqual({'class_name': 'test2'},
                         db.quota_class_get_all_by_name(self.ctxt, 'test2'))


class DBAPIQuotaTestCase(BaseTest):

    """Tests for db.api.reservation_* methods."""

    def test_quota_create(self):
        quota = db.quota_create(self.ctxt, 'project1', 'resource', 99)
        self.assertEqual(quota.resource, 'resource')
        self.assertEqual(quota.hard_limit, 99)
        self.assertEqual(quota.project_id, 'project1')

    def test_quota_get(self):
        quota = db.quota_create(self.ctxt, 'project1', 'resource', 99)
        quota_db = db.quota_get(self.ctxt, 'project1', 'resource')
        self._assertEqualObjects(quota, quota_db)

    def test_quota_get_all_by_project(self):
        for i in range(3):
            for j in range(3):
                db.quota_create(self.ctxt, 'proj%d' % i, 'res%d' % j, j)
        for i in range(3):
            quotas_db = db.quota_get_all_by_project(self.ctxt, 'proj%d' % i)
            self.assertEqual(quotas_db, {'project_id': 'proj%d' % i,
                                         'res0': 0,
                                         'res1': 1,
                                         'res2': 2})

    def test_quota_update(self):
        db.quota_create(self.ctxt, 'project1', 'resource1', 41)
        db.quota_update(self.ctxt, 'project1', 'resource1', 42)
        quota = db.quota_get(self.ctxt, 'project1', 'resource1')
        self.assertEqual(quota.hard_limit, 42)
        self.assertEqual(quota.resource, 'resource1')
        self.assertEqual(quota.project_id, 'project1')

    def test_quota_update_nonexistent(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
                          db.quota_update,
                          self.ctxt,
                          'project1',
                          'resource1',
                          42)

    def test_quota_get_nonexistent(self):
        self.assertRaises(exception.ProjectQuotaNotFound,
                          db.quota_get,
                          self.ctxt,
                          'project1',
                          'resource1')

    def test_quota_reserve(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        self.assertEqual(len(reservations), 2)
        res_names = ['gigabytes', 'volumes']
        for uuid in reservations:
            reservation = db.reservation_get(self.ctxt, uuid)
            self.assertIn(reservation.resource, res_names)
            res_names.remove(reservation.resource)

    def test_quota_destroy(self):
        db.quota_create(self.ctxt, 'project1', 'resource1', 41)
        self.assertIsNone(db.quota_destroy(self.ctxt, 'project1',
                                           'resource1'))
        self.assertRaises(exception.ProjectQuotaNotFound, db.quota_get,
                          self.ctxt, 'project1', 'resource1')

    def test_quota_destroy_all_by_project(self):
        reservations = _quota_reserve(self.ctxt, 'project1')
        db.quota_destroy_all_by_project(self.ctxt, 'project1')
        self.assertEqual(db.quota_get_all_by_project(self.ctxt, 'project1'),
                         {'project_id': 'project1'})
        self.assertEqual(db.quota_usage_get_all_by_project(self.ctxt,
                                                           'project1'),
                         {'project_id': 'project1'})
        for r in reservations:
            self.assertRaises(exception.ReservationNotFound,
                              db.reservation_get,
                              self.ctxt,
                              r)

    def test_quota_usage_get_nonexistent(self):
        self.assertRaises(exception.QuotaUsageNotFound,
                          db.quota_usage_get,
                          self.ctxt,
                          'p1',
                          'nonexitent_resource')

    def test_quota_usage_get(self):
        reservations = _quota_reserve(self.ctxt, 'p1')
        quota_usage = db.quota_usage_get(self.ctxt, 'p1', 'gigabytes')
        expected = {'resource': 'gigabytes', 'project_id': 'p1',
                    'in_use': 0, 'reserved': 2, 'total': 2}
        for key, value in expected.iteritems():
            self.assertEqual(value, quota_usage[key], key)

    def test_quota_usage_get_all_by_project(self):
        reservations = _quota_reserve(self.ctxt, 'p1')
        expected = {'project_id': 'p1',
                    'volumes': {'in_use': 0, 'reserved': 1},
                    'gigabytes': {'in_use': 0, 'reserved': 2}}
        self.assertEqual(expected, db.quota_usage_get_all_by_project(
                         self.ctxt, 'p1'))


class DBAPIIscsiTargetTestCase(BaseTest):

    """Unit tests for cinder.db.api.iscsi_target_*."""

    def _get_base_values(self):
        return {'target_num': 10, 'host': 'fake_host'}

    def test_iscsi_target_create_safe(self):
        target = db.iscsi_target_create_safe(self.ctxt,
                                             self._get_base_values())
        self.assertTrue(target['id'])
        self.assertEqual(target['host'], 'fake_host')
        self.assertEqual(target['target_num'], 10)

    def test_iscsi_target_count_by_host(self):
        for i in range(3):
            values = self._get_base_values()
            values['target_num'] += i
            db.iscsi_target_create_safe(self.ctxt, values)
        self.assertEqual(db.iscsi_target_count_by_host(self.ctxt, 'fake_host'),
                         3)

    @test.testtools.skip("bug 1187367")
    def test_integrity_error(self):
        db.iscsi_target_create_safe(self.ctxt, self._get_base_values())
        self.assertFalse(db.iscsi_target_create_safe(self.ctxt,
                                                     self._get_base_values()))


class DBAPIBackupTestCase(BaseTest):

    """Tests for db.api.backup_* methods."""

    _ignored_keys = ['id', 'deleted', 'deleted_at', 'created_at', 'updated_at']

    def setUp(self):
        super(DBAPIBackupTestCase, self).setUp()
        self.created = [db.backup_create(self.ctxt, values)
                        for values in self._get_values()]

    def _get_values(self, one=False):
        base_values = {
            'user_id': 'user',
            'project_id': 'project',
            'volume_id': 'volume',
            'host': 'host',
            'availability_zone': 'zone',
            'display_name': 'display',
            'display_description': 'description',
            'container': 'container',
            'status': 'status',
            'fail_reason': 'test',
            'service_metadata': 'metadata',
            'service': 'service',
            'size': 1000,
            'object_count': 100}
        if one:
            return base_values

        def compose(val, step):
            if isinstance(val, str):
                step = str(step)
            return val + step

        return [dict([(k, compose(v, i)) for k, v in base_values.items()])
                for i in range(1, 4)]

    def test_backup_create(self):
        values = self._get_values()
        for i, backup in enumerate(self.created):
            self.assertTrue(backup['id'])
            self._assertEqualObjects(values[i], backup, self._ignored_keys)

    def test_backup_get(self):
        for backup in self.created:
            backup_get = db.backup_get(self.ctxt, backup['id'])
            self._assertEqualObjects(backup, backup_get)

    def tests_backup_get_all(self):
        all_backups = db.backup_get_all(self.ctxt)
        self._assertEqualListsOfObjects(self.created, all_backups)

    def test_backup_get_all_by_host(self):
        byhost = db.backup_get_all_by_host(self.ctxt,
                                           self.created[1]['host'])
        self._assertEqualObjects(self.created[1], byhost[0])

    def test_backup_get_all_by_project(self):
        byproj = db.backup_get_all_by_project(self.ctxt,
                                              self.created[1]['project_id'])
        self._assertEqualObjects(self.created[1], byproj[0])

    def test_backup_update_nonexistent(self):
        self.assertRaises(exception.BackupNotFound,
                          db.backup_update,
                          self.ctxt, 'nonexistent', {})

    def test_backup_update(self):
        updated_values = self._get_values(one=True)
        update_id = self.created[1]['id']
        updated_backup = db.backup_update(self.ctxt, update_id,
                                          updated_values)
        self._assertEqualObjects(updated_values, updated_backup,
                                 self._ignored_keys)

    def test_backup_destroy(self):
        for backup in self.created:
            db.backup_destroy(self.ctxt, backup['id'])
        self.assertFalse(db.backup_get_all(self.ctxt))

    def test_backup_not_found(self):
        self.assertRaises(exception.BackupNotFound, db.backup_get, self.ctxt,
                          'notinbase')
