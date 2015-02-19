#    Copyright 2014 Red Hat, Inc.
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

import datetime

import iso8601
import mock
import netaddr

from nova import exception
from nova.objects import fixed_ip
from nova.openstack.common import timeutils
from nova.tests import fake_instance
from nova.tests.objects import test_network
from nova.tests.objects import test_objects


fake_fixed_ip = {
    'created_at': None,
    'updated_at': None,
    'deleted_at': None,
    'deleted': False,
    'id': 123,
    'address': '192.168.1.100',
    'network_id': None,
    'virtual_interface_id': None,
    'instance_uuid': None,
    'allocated': False,
    'leased': False,
    'reserved': False,
    'host': None,
    }


class _TestFixedIPObject(object):
    def _compare(self, obj, db_obj):
        for field in obj.fields:
            if field is 'virtual_interface':
                continue
            if field in fixed_ip.FIXED_IP_OPTIONAL_ATTRS:
                if obj.obj_attr_is_set(field) and db_obj[field] is not None:
                    obj_val = obj[field].uuid
                    db_val = db_obj[field]['uuid']
                else:
                    continue
            else:
                obj_val = obj[field]
                db_val = db_obj[field]
            if isinstance(obj_val, netaddr.IPAddress):
                obj_val = str(obj_val)
            self.assertEqual(db_val, obj_val)

    @mock.patch('nova.db.fixed_ip_get')
    def test_get_by_id(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_id(self.context, 123)
        get.assert_called_once_with(self.context, 123, get_network=False)
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_get')
    @mock.patch('nova.db.network_get')
    def test_get_by_id_with_extras(self, network_get, fixed_get):
        db_fixed = dict(fake_fixed_ip,
                        network=test_network.fake_network)
        fixed_get.return_value = db_fixed
        fixedip = fixed_ip.FixedIP.get_by_id(self.context, 123,
                                             expected_attrs=['network'])
        fixed_get.assert_called_once_with(self.context, 123, get_network=True)
        self._compare(fixedip, db_fixed)
        self.assertEqual(db_fixed['network']['uuid'], fixedip.network.uuid)
        self.assertFalse(network_get.called)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    def test_get_by_address(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_address(self.context, '1.2.3.4')
        get.assert_called_once_with(self.context, '1.2.3.4',
                                    columns_to_join=[])
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.instance_get')
    def test_get_by_address_with_extras(self, instance_get, network_get,
                                        fixed_get):
        db_fixed = dict(fake_fixed_ip, network=test_network.fake_network,
                        instance=fake_instance.fake_db_instance())
        fixed_get.return_value = db_fixed
        fixedip = fixed_ip.FixedIP.get_by_address(self.context, '1.2.3.4',
                                                  expected_attrs=['network',
                                                                  'instance'])
        fixed_get.assert_called_once_with(self.context, '1.2.3.4',
                                          columns_to_join=['network',
                                                           'instance'])
        self._compare(fixedip, db_fixed)
        self.assertEqual(db_fixed['network']['uuid'], fixedip.network.uuid)
        self.assertEqual(db_fixed['instance']['uuid'], fixedip.instance.uuid)
        self.assertFalse(network_get.called)
        self.assertFalse(instance_get.called)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.instance_get')
    def test_get_by_address_with_extras_deleted_instance(self, instance_get,
                                                         network_get,
                                                         fixed_get):
        db_fixed = dict(fake_fixed_ip, network=test_network.fake_network,
                        instance=None)
        fixed_get.return_value = db_fixed
        fixedip = fixed_ip.FixedIP.get_by_address(self.context, '1.2.3.4',
                                                  expected_attrs=['network',
                                                                  'instance'])
        fixed_get.assert_called_once_with(self.context, '1.2.3.4',
                                          columns_to_join=['network',
                                                           'instance'])
        self._compare(fixedip, db_fixed)
        self.assertEqual(db_fixed['network']['uuid'], fixedip.network.uuid)
        self.assertIsNone(fixedip.instance)
        self.assertFalse(network_get.called)
        self.assertFalse(instance_get.called)

    @mock.patch('nova.db.fixed_ip_get_by_floating_address')
    def test_get_by_floating_ip(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_floating_address(self.context,
                                                           '1.2.3.4')
        get.assert_called_once_with(self.context, '1.2.3.4')
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_get_by_network_host')
    def test_get_by_network_and_host(self, get):
        get.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.get_by_network_and_host(self.context,
                                                           123, 'host')
        get.assert_called_once_with(self.context, 123, 'host')
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_associate')
    def test_associate(self, associate):
        associate.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.associate(self.context, '1.2.3.4',
                                             'fake-uuid')
        associate.assert_called_with(self.context, '1.2.3.4', 'fake-uuid',
                                     network_id=None, reserved=False)
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_associate_pool')
    def test_associate_pool(self, associate):
        associate.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP.associate_pool(self.context, 123,
                                                  'fake-uuid', 'host')
        associate.assert_called_with(self.context, 123,
                                     instance_uuid='fake-uuid',
                                     host='host')
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_disassociate')
    def test_disassociate_by_address(self, disassociate):
        fixed_ip.FixedIP.disassociate_by_address(self.context, '1.2.3.4')
        disassociate.assert_called_with(self.context, '1.2.3.4')

    @mock.patch('nova.db.fixed_ip_disassociate_all_by_timeout')
    def test_disassociate_all_by_timeout(self, disassociate):
        now = timeutils.utcnow()
        now_tz = timeutils.parse_isotime(
            timeutils.isotime(now)).replace(
                tzinfo=iso8601.iso8601.Utc())
        disassociate.return_value = 123
        result = fixed_ip.FixedIP.disassociate_all_by_timeout(self.context,
                                                              'host', now)
        self.assertEqual(123, result)
        # NOTE(danms): be pedantic about timezone stuff
        args, kwargs = disassociate.call_args_list[0]
        self.assertEqual(now_tz, args[2])
        self.assertEqual((self.context, 'host'), args[:2])
        self.assertEqual({}, kwargs)

    @mock.patch('nova.db.fixed_ip_create')
    def test_create(self, create):
        create.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP(address='1.2.3.4')
        fixedip.create(self.context)
        create.assert_called_once_with(
            self.context, {'address': '1.2.3.4'})
        self._compare(fixedip, fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_update')
    def test_save(self, update):
        update.return_value = fake_fixed_ip
        fixedip = fixed_ip.FixedIP(context=self.context, address='1.2.3.4',
                                   instance_uuid='fake-uuid')
        self.assertRaises(exception.ObjectActionError, fixedip.save)
        fixedip.obj_reset_changes(['address'])
        fixedip.save()
        update.assert_called_once_with(self.context, '1.2.3.4',
                                       {'instance_uuid': 'fake-uuid'})

    @mock.patch('nova.db.fixed_ip_disassociate')
    def test_disassociate(self, disassociate):
        fixedip = fixed_ip.FixedIP(context=self.context, address='1.2.3.4',
                                   instance_uuid='fake-uuid')
        fixedip.obj_reset_changes()
        fixedip.disassociate()
        disassociate.assert_called_once_with(self.context, '1.2.3.4')
        self.assertIsNone(fixedip.instance_uuid)

    @mock.patch('nova.db.fixed_ip_get_all')
    def test_get_all(self, get_all):
        get_all.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_all(self.context)
        self.assertEqual(1, len(fixedips))
        get_all.assert_called_once_with(self.context)
        self._compare(fixedips[0], fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_get_by_instance')
    def test_get_by_instance(self, get):
        get.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_by_instance_uuid(self.context,
                                                             'fake-uuid')
        self.assertEqual(1, len(fixedips))
        get.assert_called_once_with(self.context, 'fake-uuid')
        self._compare(fixedips[0], fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_get_by_host')
    def test_get_by_host(self, get):
        get.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_by_host(self.context, 'host')
        self.assertEqual(1, len(fixedips))
        get.assert_called_once_with(self.context, 'host')
        self._compare(fixedips[0], fake_fixed_ip)

    @mock.patch('nova.db.fixed_ips_by_virtual_interface')
    def test_get_by_virtual_interface_id(self, get):
        get.return_value = [fake_fixed_ip]
        fixedips = fixed_ip.FixedIPList.get_by_virtual_interface_id(
            self.context, 123)
        self.assertEqual(1, len(fixedips))
        get.assert_called_once_with(self.context, 123)
        self._compare(fixedips[0], fake_fixed_ip)

    @mock.patch('nova.db.fixed_ip_bulk_create')
    def test_bulk_create(self, bulk):
        fixed_ips = [fixed_ip.FixedIP(address='192.168.1.1'),
                     fixed_ip.FixedIP(address='192.168.1.2')]
        fixed_ip.FixedIPList.bulk_create(self.context, fixed_ips)
        bulk.assert_called_once_with(self.context,
                                     [{'address': '192.168.1.1'},
                                      {'address': '192.168.1.2'}])

    @mock.patch('nova.db.network_get_associated_fixed_ips')
    def test_get_by_network(self, get):
        info = {'address': '1.2.3.4',
                'instance_uuid': 'fake-uuid',
                'network_id': 0,
                'vif_id': 1,
                'vif_address': 'de:ad:be:ee:f0:00',
                'instance_hostname': 'fake-host',
                'instance_updated': datetime.datetime(1955, 11, 5),
                'instance_created': datetime.datetime(1955, 11, 5),
                'allocated': True,
                'leased': True,
                }
        get.return_value = [info]
        fixed_ips = fixed_ip.FixedIPList.get_by_network(
            self.context, {'id': 0}, host='fake-host')
        get.assert_called_once_with(self.context, 0, host='fake-host')
        self.assertEqual(1, len(fixed_ips))
        fip = fixed_ips[0]
        self.assertEqual('1.2.3.4', str(fip.address))
        self.assertEqual('fake-uuid', fip.instance_uuid)
        self.assertEqual(0, fip.network_id)
        self.assertEqual(1, fip.virtual_interface_id)
        self.assertTrue(fip.allocated)
        self.assertTrue(fip.leased)
        self.assertEqual('fake-uuid', fip.instance.uuid)
        self.assertEqual('fake-host', fip.instance.hostname)
        self.assertIsInstance(fip.instance.created_at, datetime.datetime)
        self.assertIsInstance(fip.instance.updated_at, datetime.datetime)
        self.assertEqual(1, fip.virtual_interface.id)
        self.assertEqual(info['vif_address'], fip.virtual_interface.address)


class TestFixedIPObject(test_objects._LocalTest,
                        _TestFixedIPObject):
    pass


class TestRemoteFixedIPObject(test_objects._RemoteTest,
                              _TestFixedIPObject):
    pass
