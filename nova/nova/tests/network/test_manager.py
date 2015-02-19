# Copyright 2011 Rackspace
# Copyright (c) 2011 X.commerce, a business unit of eBay Inc.
# Copyright 2013 IBM Corp.
# All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import fixtures
import mock
import mox
import netaddr
from oslo.config import cfg
from oslo import messaging

from nova import context
from nova import db
from nova.db.sqlalchemy import models
from nova import exception
from nova import ipv6
from nova.network import floating_ips
from nova.network import linux_net
from nova.network import manager as network_manager
from nova.network import model as net_model
from nova.objects import fixed_ip as fixed_ip_obj
from nova.objects import floating_ip as floating_ip_obj
from nova.objects import instance as instance_obj
from nova.objects import network as network_obj
from nova.objects import quotas as quotas_obj
from nova.openstack.common.db import exception as db_exc
from nova.openstack.common import importutils
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova import test
from nova.tests import fake_instance
from nova.tests import fake_ldap
from nova.tests import fake_network
from nova.tests import matchers
from nova.tests.objects import test_fixed_ip
from nova.tests.objects import test_floating_ip
from nova.tests.objects import test_network
from nova.tests.objects import test_service
from nova import utils

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


HOST = "testhost"
FAKEUUID = "aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa"


fake_inst = fake_instance.fake_db_instance


networks = [{'id': 0,
             'uuid': FAKEUUID,
             'label': 'test0',
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.0.0/24',
             'cidr_v6': '2001:db8::/64',
             'gateway_v6': '2001:db8::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa0',
             'bridge_interface': 'fake_fa0',
             'gateway': '192.168.0.1',
             'broadcast': '192.168.0.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'vlan': None,
             'host': HOST,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.0.2',
             'vpn_public_port': '22',
             'vpn_private_address': '10.0.0.2'},
            {'id': 1,
             'uuid': 'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
             'label': 'test1',
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.1.0/24',
             'cidr_v6': '2001:db9::/64',
             'gateway_v6': '2001:db9::1',
             'netmask_v6': '64',
             'netmask': '255.255.255.0',
             'bridge': 'fa1',
             'bridge_interface': 'fake_fa1',
             'gateway': '192.168.1.1',
             'broadcast': '192.168.1.255',
             'dns1': '192.168.0.1',
             'dns2': '192.168.0.2',
             'vlan': None,
             'host': HOST,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.1.2',
             'vpn_public_port': '22',
             'vpn_private_address': '10.0.0.2'}]

fixed_ips = [{'id': 0,
              'network_id': 0,
              'address': '192.168.0.100',
              'instance_uuid': 0,
              'allocated': False,
              'virtual_interface_id': 0,
              'floating_ips': []},
             {'id': 0,
              'network_id': 1,
              'address': '192.168.1.100',
              'instance_uuid': 0,
              'allocated': False,
              'virtual_interface_id': 0,
              'floating_ips': []},
             {'id': 0,
              'network_id': 1,
              'address': '2001:db9:0:1::10',
              'instance_uuid': 0,
              'allocated': False,
              'virtual_interface_id': 0,
              'floating_ips': []}]


flavor = {'id': 0,
          'rxtx_cap': 3}


floating_ip_fields = {'id': 0,
                      'address': '192.168.10.100',
                      'pool': 'nova',
                      'interface': 'eth0',
                      'fixed_ip_id': 0,
                      'project_id': None,
                      'auto_assigned': False}

vifs = [{'id': 0,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:00',
         'uuid': '00000000-0000-0000-0000-0000000000000000',
         'network_id': 0,
         'instance_uuid': 0},
        {'id': 1,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:01',
         'uuid': '00000000-0000-0000-0000-0000000000000001',
         'network_id': 1,
         'instance_uuid': 0},
        {'id': 2,
         'created_at': None,
         'updated_at': None,
         'deleted_at': None,
         'deleted': 0,
         'address': 'DE:AD:BE:EF:00:02',
         'uuid': '00000000-0000-0000-0000-0000000000000002',
         'network_id': 2,
         'instance_uuid': 0}]


class FlatNetworkTestCase(test.TestCase):
    def setUp(self):
        super(FlatNetworkTestCase, self).setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.flags(log_dir=self.tempdir)
        self.flags(use_local=True, group='conductor')
        self.network = network_manager.FlatManager(host=HOST)
        self.network.instance_dns_domain = ''
        self.network.db = db
        self.context = context.RequestContext('testuser', 'testproject',
                                              is_admin=False)

    def test_get_instance_nw_info(self):
        fake_get_instance_nw_info = fake_network.fake_get_instance_nw_info

        nw_info = fake_get_instance_nw_info(self.stubs, 0, 2)
        self.assertFalse(nw_info)

        nw_info = fake_get_instance_nw_info(self.stubs, 1, 2)

        for i, vif in enumerate(nw_info):
            nid = i + 1
            check = {'bridge': 'fake_br%d' % nid,
                     'cidr': '192.168.%s.0/24' % nid,
                     'cidr_v6': '2001:db8:0:%x::/64' % nid,
                     'id': '00000000-0000-0000-0000-00000000000000%02d' % nid,
                     'multi_host': False,
                     'injected': False,
                     'bridge_interface': None,
                     'vlan': None,
                     'broadcast': '192.168.%d.255' % nid,
                     'dhcp_server': '192.168.1.1',
                     'dns': ['192.168.%d.3' % nid, '192.168.%d.4' % nid],
                     'gateway': '192.168.%d.1' % nid,
                     'gateway_v6': '2001:db8:0:1::1',
                     'label': 'test%d' % nid,
                     'mac': 'DE:AD:BE:EF:00:%02x' % nid,
                     'rxtx_cap': 30,
                     'vif_type': net_model.VIF_TYPE_BRIDGE,
                     'vif_devname': None,
                     'vif_uuid':
                        '00000000-0000-0000-0000-00000000000000%02d' % nid,
                     'ovs_interfaceid': None,
                     'qbh_params': None,
                     'qbg_params': None,
                     'should_create_vlan': False,
                     'should_create_bridge': False,
                     'ip': '192.168.%d.%03d' % (nid, nid + 99),
                     'ip_v6': '2001:db8:0:1::%x' % nid,
                     'netmask': '255.255.255.0',
                     'netmask_v6': 64,
                     'physical_network': None,
                      }

            network = vif['network']
            net_v4 = vif['network']['subnets'][0]
            net_v6 = vif['network']['subnets'][1]

            vif_dict = dict(bridge=network['bridge'],
                            cidr=net_v4['cidr'],
                            cidr_v6=net_v6['cidr'],
                            id=vif['id'],
                            multi_host=network.get_meta('multi_host', False),
                            injected=network.get_meta('injected', False),
                            bridge_interface=
                                network.get_meta('bridge_interface'),
                            vlan=network.get_meta('vlan'),
                            broadcast=str(net_v4.as_netaddr().broadcast),
                            dhcp_server=network.get_meta('dhcp_server',
                                net_v4['gateway']['address']),
                            dns=[ip['address'] for ip in net_v4['dns']],
                            gateway=net_v4['gateway']['address'],
                            gateway_v6=net_v6['gateway']['address'],
                            label=network['label'],
                            mac=vif['address'],
                            rxtx_cap=vif.get_meta('rxtx_cap'),
                            vif_type=vif['type'],
                            vif_devname=vif.get('devname'),
                            vif_uuid=vif['id'],
                            ovs_interfaceid=vif.get('ovs_interfaceid'),
                            qbh_params=vif.get('qbh_params'),
                            qbg_params=vif.get('qbg_params'),
                            should_create_vlan=
                                network.get_meta('should_create_vlan', False),
                            should_create_bridge=
                                network.get_meta('should_create_bridge',
                                                  False),
                            ip=net_v4['ips'][i]['address'],
                            ip_v6=net_v6['ips'][i]['address'],
                            netmask=str(net_v4.as_netaddr().netmask),
                            netmask_v6=net_v6.as_netaddr()._prefixlen,
                            physical_network=
                                network.get_meta('physical_network', None))

            self.assertThat(vif_dict, matchers.DictMatches(check))

    def test_validate_networks(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        self.mox.StubOutWithMock(db, 'fixed_ip_get_by_address')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100')]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])

        ip = dict(test_fixed_ip.fake_fixed_ip, **fixed_ips[1])
        ip['network'] = dict(test_network.fake_network,
                             **networks[1])
        ip['instance_uuid'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(ip)
        ip = dict(test_fixed_ip.fake_fixed_ip, **fixed_ips[0])
        ip['network'] = dict(test_network.fake_network,
                             **networks[0])
        ip['instance_uuid'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(ip)

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_valid_fixed_ipv6(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        self.mox.StubOutWithMock(db, 'fixed_ip_get_by_address')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '2001:db9:0:1::10')]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **networks[1])])

        ip = dict(test_fixed_ip.fake_fixed_ip, **fixed_ips[2])
        ip['network'] = dict(test_network.fake_network,
                             **networks[1])
        ip['instance_uuid'] = None
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(ip)

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_reserved(self):
        context_admin = context.RequestContext('testuser', 'testproject',
                                              is_admin=True)
        nets = self.network.create_networks(context_admin, 'fake',
                                       '192.168.0.0/24', False, 1,
                                       256, None, None, None, None, None)
        self.assertEqual(1, len(nets))
        network = nets[0]
        self.assertEqual(3, db.network_count_reserved_ips(context_admin,
                        network['id']))

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(self.context, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100.1'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100.1')]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks, self.context,
                          requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               ''),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '')]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          self.context, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               None),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               None)]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    @mock.patch('nova.objects.quotas.Quotas.reserve')
    def test_add_fixed_ip_instance_using_id_without_vpn(self, reserve):
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                lambda *a, **kw: None)
        self.mox.StubOutWithMock(db, 'network_get')
        self.mox.StubOutWithMock(db, 'network_update')
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(self.network, 'get_instance_nw_info')

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.101')
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   instance_uuid=mox.IgnoreArg(),
                                   host=None).AndReturn(fixed)

        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])

        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())

        inst = fake_inst(display_name=HOST, uuid=FAKEUUID)
        db.instance_get_by_uuid(self.context,
                                mox.IgnoreArg(), use_slave=False,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(inst)

        db.network_get(mox.IgnoreArg(),
                       mox.IgnoreArg(),
                       project_only=mox.IgnoreArg()
                       ).AndReturn(dict(test_network.fake_network,
                                        **networks[0]))
        db.network_update(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

        self.network.get_instance_nw_info(mox.IgnoreArg(), mox.IgnoreArg(),
                                          mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, FAKEUUID, HOST,
                                              networks[0]['id'])
        exp_project, exp_user = quotas_obj.ids_from_instance(self.context,
                                                             inst)
        reserve.assert_called_once_with(self.context, fixed_ips=1,
                                        project_id=exp_project,
                                        user_id=exp_user)

    @mock.patch('nova.objects.quotas.Quotas.reserve')
    def test_add_fixed_ip_instance_using_uuid_without_vpn(self, reserve):
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                lambda *a, **kw: None)
        self.mox.StubOutWithMock(db, 'network_get_by_uuid')
        self.mox.StubOutWithMock(db, 'network_update')
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(self.network, 'get_instance_nw_info')

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.101')
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   instance_uuid=mox.IgnoreArg(),
                                   host=None).AndReturn(fixed)

        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])

        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())

        inst = fake_inst(display_name=HOST, uuid=FAKEUUID)
        db.instance_get_by_uuid(self.context,
                                mox.IgnoreArg(), use_slave=False,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(inst)

        db.network_get_by_uuid(mox.IgnoreArg(),
                               mox.IgnoreArg()
                               ).AndReturn(dict(test_network.fake_network,
                                                **networks[0]))
        db.network_update(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

        self.network.get_instance_nw_info(mox.IgnoreArg(), mox.IgnoreArg(),
                                          mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, FAKEUUID, HOST,
                                              networks[0]['uuid'])
        exp_project, exp_user = quotas_obj.ids_from_instance(self.context,
                                                             inst)
        reserve.assert_called_once_with(self.context, fixed_ips=1,
                                        project_id=exp_project,
                                        user_id=exp_user)

    def test_mini_dns_driver(self):
        zone1 = "example.org"
        zone2 = "example.com"
        driver = self.network.instance_dns_manager
        driver.create_entry("hostone", "10.0.0.1", "A", zone1)
        driver.create_entry("hosttwo", "10.0.0.2", "A", zone1)
        driver.create_entry("hostthree", "10.0.0.3", "A", zone1)
        driver.create_entry("hostfour", "10.0.0.4", "A", zone1)
        driver.create_entry("hostfive", "10.0.0.5", "A", zone2)

        driver.delete_entry("hostone", zone1)
        driver.modify_address("hostfour", "10.0.0.1", zone1)
        driver.modify_address("hostthree", "10.0.0.1", zone1)
        names = driver.get_entries_by_address("10.0.0.1", zone1)
        self.assertEqual(len(names), 2)
        self.assertIn('hostthree', names)
        self.assertIn('hostfour', names)

        names = driver.get_entries_by_address("10.0.0.5", zone2)
        self.assertEqual(len(names), 1)
        self.assertIn('hostfive', names)

        addresses = driver.get_entries_by_name("hosttwo", zone1)
        self.assertEqual(len(addresses), 1)
        self.assertIn('10.0.0.2', addresses)

        self.assertRaises(exception.InvalidInput,
                driver.create_entry,
                "hostname",
                "10.10.10.10",
                "invalidtype",
                zone1)

    def test_mini_dns_driver_with_mixed_case(self):
        zone1 = "example.org"
        driver = self.network.instance_dns_manager
        driver.create_entry("HostTen", "10.0.0.10", "A", zone1)
        addresses = driver.get_entries_by_address("10.0.0.10", zone1)
        self.assertEqual(len(addresses), 1)
        for n in addresses:
            driver.delete_entry(n, zone1)
        addresses = driver.get_entries_by_address("10.0.0.10", zone1)
        self.assertEqual(len(addresses), 0)

    @mock.patch('nova.objects.quotas.Quotas.reserve')
    def test_instance_dns(self, reserve):
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                lambda *a, **kw: None)
        fixedip = dict(test_fixed_ip.fake_fixed_ip,
                       address='192.168.0.101')
        self.mox.StubOutWithMock(db, 'network_get_by_uuid')
        self.mox.StubOutWithMock(db, 'network_update')
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(self.network, 'get_instance_nw_info')

        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   instance_uuid=mox.IgnoreArg(),
                                   host=None
                                   ).AndReturn(fixedip)

        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])

        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())

        inst = fake_inst(display_name=HOST, uuid=FAKEUUID)
        db.instance_get_by_uuid(self.context,
                                mox.IgnoreArg(), use_slave=False,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(inst)

        db.network_get_by_uuid(mox.IgnoreArg(),
                               mox.IgnoreArg()
                               ).AndReturn(dict(test_network.fake_network,
                                                **networks[0]))
        db.network_update(mox.IgnoreArg(), mox.IgnoreArg(), mox.IgnoreArg())

        self.network.get_instance_nw_info(mox.IgnoreArg(), mox.IgnoreArg(),
                                          mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, FAKEUUID, HOST,
                                              networks[0]['uuid'])

        instance_manager = self.network.instance_dns_manager
        addresses = instance_manager.get_entries_by_name(HOST,
                                             self.network.instance_dns_domain)
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], fixedip['address'])
        addresses = instance_manager.get_entries_by_name(FAKEUUID,
                                              self.network.instance_dns_domain)
        self.assertEqual(len(addresses), 1)
        self.assertEqual(addresses[0], fixedip['address'])
        exp_project, exp_user = quotas_obj.ids_from_instance(self.context,
                                                             inst)
        reserve.assert_called_once_with(self.context, fixed_ips=1,
                                        project_id=exp_project,
                                        user_id=exp_user)

    def test_allocate_floating_ip(self):
        self.assertIsNone(self.network.allocate_floating_ip(self.context,
                                                            1, None))

    def test_deallocate_floating_ip(self):
        self.assertIsNone(self.network.deallocate_floating_ip(self.context,
                                                              1, None))

    def test_associate_floating_ip(self):
        self.assertIsNone(self.network.associate_floating_ip(self.context,
                                                             None, None))

    def test_disassociate_floating_ip(self):
        self.assertIsNone(self.network.disassociate_floating_ip(self.context,
                                                                None, None))

    def test_get_networks_by_uuids_ordering(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = ['bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                              'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa']
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])

        self.mox.ReplayAll()
        res = self.network._get_networks_by_uuids(self.context,
                                                  requested_networks)

        self.assertEqual(res[0]['id'], 1)
        self.assertEqual(res[1]['id'], 0)

    @mock.patch('nova.objects.instance.Instance.get_by_uuid')
    @mock.patch('nova.objects.quotas.Quotas.reserve')
    @mock.patch('nova.objects.quotas.ids_from_instance')
    def test_allocate_calculates_quota_auth(self, util_method, reserve,
                                            get_by_uuid):
        inst = instance_obj.Instance()
        get_by_uuid.return_value = inst
        reserve.side_effect = exception.OverQuota(overs='testing')
        util_method.return_value = ('foo', 'bar')
        self.assertRaises(exception.FixedIpLimitExceeded,
                          self.network.allocate_fixed_ip,
                          self.context, 123, None)
        util_method.assert_called_once_with(self.context, inst)

    @mock.patch('nova.objects.fixed_ip.FixedIP.get_by_address')
    @mock.patch('nova.objects.quotas.Quotas.reserve')
    @mock.patch('nova.objects.quotas.ids_from_instance')
    def test_deallocate_calculates_quota_auth(self, util_method, reserve,
                                              get_by_address):
        inst = instance_obj.Instance(uuid='fake-uuid')
        fip = fixed_ip_obj.FixedIP(instance_uuid='fake-uuid',
                                   virtual_interface_id=1)
        get_by_address.return_value = fip
        util_method.return_value = ('foo', 'bar')
        # This will fail right after the reserve call when it tries
        # to look up the fake instance we created above
        self.assertRaises(exception.InstanceNotFound,
                          self.network.deallocate_fixed_ip,
                          self.context, '1.2.3.4', instance=inst)
        util_method.assert_called_once_with(self.context, inst)


class VlanNetworkTestCase(test.TestCase):
    def setUp(self):
        super(VlanNetworkTestCase, self).setUp()
        self.useFixture(test.SampleNetworks())
        self.flags(use_local=True, group='conductor')
        self.network = network_manager.VlanManager(host=HOST)
        self.network.db = db
        self.context = context.RequestContext('testuser', 'testproject',
                                              is_admin=False)
        self.context_admin = context.RequestContext('testuser', 'testproject',
                                                is_admin=True)

    def test_quota_driver_type(self):
        self.assertEqual(quotas_obj.QuotasNoOp,
                         self.network.quotas_cls)

    def test_vpn_allocate_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'fixed_ip_associate')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.1')
        db.fixed_ip_associate(mox.IgnoreArg(),
                              mox.IgnoreArg(),
                              mox.IgnoreArg(),
                              network_id=mox.IgnoreArg(),
                              reserved=True).AndReturn(fixed)
        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])
        db.instance_get_by_uuid(mox.IgnoreArg(),
                                mox.IgnoreArg(), use_slave=False,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst(display_name=HOST,
                                                      uuid=FAKEUUID))
        self.mox.ReplayAll()

        network = network_obj.Network._from_db_object(
            self.context, network_obj.Network(),
            dict(test_network.fake_network, **networks[0]))
        network.vpn_private_address = '192.168.0.2'
        self.network.allocate_fixed_ip(self.context, FAKEUUID, network,
                                       vpn=True)

    def test_vpn_allocate_fixed_ip_no_network_id(self):
        network = dict(networks[0])
        network['vpn_private_address'] = '192.168.0.2'
        network['id'] = None
        instance = db.instance_create(self.context, {})
        self.assertRaises(exception.FixedIpNotFoundForNetwork,
                self.network.allocate_fixed_ip,
                self.context_admin,
                instance['uuid'],
                network,
                vpn=True)

    def test_allocate_fixed_ip(self):
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                lambda *a, **kw: None)
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.1')
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   instance_uuid=mox.IgnoreArg(),
                                   host=None).AndReturn(fixed)
        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])
        db.instance_get_by_uuid(mox.IgnoreArg(),
                                mox.IgnoreArg(), use_slave=False,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst(display_name=HOST,
                                                      uuid=FAKEUUID))
        self.mox.ReplayAll()

        network = network_obj.Network._from_db_object(
            self.context, network_obj.Network(),
            dict(test_network.fake_network, **networks[0]))
        network.vpn_private_address = '192.168.0.2'
        self.network.allocate_fixed_ip(self.context, FAKEUUID, network)

    def test_create_networks_too_big(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=4094, vlan_start=1)

    def test_create_networks_too_many(self):
        self.assertRaises(ValueError, self.network.create_networks, None,
                          num_networks=100, vlan_start=1,
                          cidr='192.168.0.1/24', network_size=100)

    def test_duplicate_vlan_raises(self):
        # VLAN 100 is already used and we force the network to be created
        # in that vlan (vlan=100).
        self.assertRaises(exception.DuplicateVlan,
                          self.network.create_networks,
                          self.context_admin, label="fake", num_networks=1,
                          vlan=100, cidr='192.168.0.1/24', network_size=100)

    def test_vlan_start(self):
        # VLAN 100 and 101 are used, so this network shoud be created in 102
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=1,
                          vlan_start=100, cidr='192.168.3.1/24',
                          network_size=100)

        self.assertEqual(networks[0]["vlan"], 102)

    def test_vlan_start_multiple(self):
        # VLAN 100 and 101 are used, so these networks shoud be created in 102
        # and 103
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=2,
                          vlan_start=100, cidr='192.168.3.1/24',
                          network_size=100)

        self.assertEqual(networks[0]["vlan"], 102)
        self.assertEqual(networks[1]["vlan"], 103)

    def test_vlan_start_used(self):
        # VLAN 100 and 101 are used, but vlan_start=99.
        networks = self.network.create_networks(
                          self.context_admin, label="fake", num_networks=1,
                          vlan_start=99, cidr='192.168.3.1/24',
                          network_size=100)

        self.assertEqual(networks[0]["vlan"], 102)

    @mock.patch('nova.db.network_get')
    def test_validate_networks(self, net_get):
        def network_get(_context, network_id, project_only='allow_none'):
            return dict(test_network.fake_network, **networks[network_id])

        net_get.side_effect = network_get
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        self.mox.StubOutWithMock(db, "fixed_ip_get_by_address")

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100')]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])

        db_fixed1 = dict(test_fixed_ip.fake_fixed_ip,
                         network_id=networks[1]['id'],
                         network=dict(test_network.fake_network,
                                      **networks[1]),
                         instance_uuid=None)
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(db_fixed1)
        db_fixed2 = dict(test_fixed_ip.fake_fixed_ip,
                         network_id=networks[0]['id'],
                         network=dict(test_network.fake_network,
                                      **networks[0]),
                         instance_uuid=None)
        db.fixed_ip_get_by_address(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   columns_to_join=mox.IgnoreArg()
                                   ).AndReturn(db_fixed2)

        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_none_requested_networks(self):
        self.network.validate_networks(self.context, None)

    def test_validate_networks_empty_requested_networks(self):
        requested_networks = []
        self.mox.ReplayAll()

        self.network.validate_networks(self.context, requested_networks)

    def test_validate_networks_invalid_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')
        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                               '192.168.1.100.1'),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa',
                               '192.168.0.100.1')]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks, self.context,
                          requested_networks)

    def test_validate_networks_empty_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', ''),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', '')]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])
        self.mox.ReplayAll()

        self.assertRaises(exception.FixedIpInvalid,
                          self.network.validate_networks,
                          self.context, requested_networks)

    def test_validate_networks_none_fixed_ip(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = [('bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb', None),
                              ('aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa', None)]
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])
        self.mox.ReplayAll()
        self.network.validate_networks(self.context, requested_networks)

    def test_floating_ip_owned_by_project(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        # raises because floating_ip project_id is None
        floating_ip = floating_ip_obj.FloatingIP(address='10.0.0.1',
                                                 project_id=None)
        self.assertRaises(exception.NotAuthorized,
                          self.network._floating_ip_owned_by_project,
                          ctxt,
                          floating_ip)

        # raises because floating_ip project_id is not equal to ctxt project_id
        floating_ip = floating_ip_obj.FloatingIP(
            address='10.0.0.1', project_id=ctxt.project_id + '1')
        self.assertRaises(exception.NotAuthorized,
                          self.network._floating_ip_owned_by_project,
                          ctxt,
                          floating_ip)

        # does not raise (floating ip is owned by ctxt project)
        floating_ip = floating_ip_obj.FloatingIP(address='10.0.0.1',
                                                 project_id=ctxt.project_id)
        self.network._floating_ip_owned_by_project(ctxt, floating_ip)

        ctxt = context.RequestContext(None, None,
                                      is_admin=True)

        # does not raise (ctxt is admin)
        floating_ip = floating_ip_obj.FloatingIP(address='10.0.0.1',
                                                 project_id=None)
        self.network._floating_ip_owned_by_project(ctxt, floating_ip)

        # does not raise (ctxt is admin)
        floating_ip = floating_ip_obj.FloatingIP(address='10.0.0.1',
                                                 project_id='testproject')
        self.network._floating_ip_owned_by_project(ctxt, floating_ip)

    def test_allocate_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake_allocate_address(*args, **kwargs):
            return {'address': '10.0.0.1', 'project_id': ctxt.project_id}

        self.stubs.Set(self.network.db, 'floating_ip_allocate_address',
                       fake_allocate_address)

        self.network.allocate_floating_ip(ctxt, ctxt.project_id)

    def test_deallocate_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake1(*args, **kwargs):
            pass

        def fake2(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1', fixed_ip_id=1)

        def fake3(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1', fixed_ip_id=None,
                        project_id=ctxt.project_id)

        self.stubs.Set(self.network.db, 'floating_ip_deallocate', fake1)
        self.stubs.Set(self.network, '_floating_ip_owned_by_project', fake1)

        # this time should raise because floating ip is associated to fixed_ip
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake2)
        self.assertRaises(exception.FloatingIpAssociated,
                          self.network.deallocate_floating_ip,
                          ctxt,
                          mox.IgnoreArg())

        # this time should not raise
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake3)
        self.network.deallocate_floating_ip(ctxt, ctxt.project_id)

    @mock.patch('nova.db.fixed_ip_get')
    def test_associate_floating_ip(self, fixed_get):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake1(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        network=test_network.fake_network)

        # floating ip that's already associated
        def fake2(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=1)

        # floating ip that isn't associated
        def fake3(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=None)

        # fixed ip with remote host
        def fake4(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=123)

        def fake4_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False, host='jibberjabber')

        # fixed ip with local host
        def fake5(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=1234)

        def fake5_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False, host='testhost')

        def fake6(ctxt, method, **kwargs):
            self.local = False

        def fake7(*args, **kwargs):
            self.local = True

        def fake8(*args, **kwargs):
            raise processutils.ProcessExecutionError('',
                    'Cannot find device "em0"\n')

        def fake9(*args, **kwargs):
            raise test.TestingException()

        # raises because interface doesn't exist
        self.stubs.Set(self.network.db,
                       'floating_ip_fixed_ip_associate',
                       fake1)
        self.stubs.Set(self.network.db, 'floating_ip_disassociate', fake1)
        self.stubs.Set(self.network.driver, 'ensure_floating_forward', fake8)
        self.assertRaises(exception.NoFloatingIpInterface,
                          self.network._associate_floating_ip,
                          ctxt,
                          '1.2.3.4',
                          '1.2.3.5',
                          mox.IgnoreArg(),
                          mox.IgnoreArg())

        self.stubs.Set(self.network, '_floating_ip_owned_by_project', fake1)

        # raises because floating_ip is already associated to a fixed_ip
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake2)
        self.stubs.Set(self.network, 'disassociate_floating_ip', fake9)

        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address='1.2.3.4',
                                      instance_uuid='fake_uuid',
                                      network=test_network.fake_network)

        # doesn't raise because we exit early if the address is the same
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(), '1.2.3.4')

        # raises because we call disassociate which is mocked
        self.assertRaises(test.TestingException,
                          self.network.associate_floating_ip,
                          ctxt,
                          mox.IgnoreArg(),
                          'new')

        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake3)

        # does not raise and makes call remotely
        self.local = True
        self.stubs.Set(self.network.db, 'fixed_ip_get_by_address', fake4)
        self.stubs.Set(self.network.db, 'network_get', fake4_network)
        self.stubs.Set(self.network.network_rpcapi.client, 'prepare',
                       lambda **kw: self.network.network_rpcapi.client)
        self.stubs.Set(self.network.network_rpcapi.client, 'call', fake6)
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(),
                                                 mox.IgnoreArg())
        self.assertFalse(self.local)

        # does not raise and makes call locally
        self.local = False
        self.stubs.Set(self.network.db, 'fixed_ip_get_by_address', fake5)
        self.stubs.Set(self.network.db, 'network_get', fake5_network)
        self.stubs.Set(self.network, '_associate_floating_ip', fake7)
        self.network.associate_floating_ip(ctxt, mox.IgnoreArg(),
                                                 mox.IgnoreArg())
        self.assertTrue(self.local)

    def test_add_floating_ip_nat_before_bind(self):
        # Tried to verify order with documented mox record/verify
        # functionality, but it doesn't seem to work since I can't make it
        # fail.  I'm using stubs and a flag for now, but if this mox feature
        # can be made to work, it would be a better way to test this.
        #
        # self.mox.StubOutWithMock(self.network.driver,
        #                          'ensure_floating_forward')
        # self.mox.StubOutWithMock(self.network.driver, 'bind_floating_ip')
        #
        # self.network.driver.ensure_floating_forward(mox.IgnoreArg(),
        #                                             mox.IgnoreArg(),
        #                                             mox.IgnoreArg(),
        #                                             mox.IgnoreArg())
        # self.network.driver.bind_floating_ip(mox.IgnoreArg(),
        #                                      mox.IgnoreArg())
        # self.mox.ReplayAll()

        nat_called = [False]

        def fake_nat(*args, **kwargs):
            nat_called[0] = True

        def fake_bind(*args, **kwargs):
            self.assertTrue(nat_called[0])

        self.stubs.Set(self.network.driver,
                       'ensure_floating_forward',
                       fake_nat)
        self.stubs.Set(self.network.driver, 'bind_floating_ip', fake_bind)

        self.network.l3driver.add_floating_ip('fakefloat',
                                              'fakefixed',
                                              'fakeiface',
                                              'fakenet')

    @mock.patch('nova.db.floating_ip_get_all_by_host')
    @mock.patch('nova.db.fixed_ip_get')
    def _test_floating_ip_init_host(self, fixed_get, floating_get,
                                    public_interface, expected_arg):

        floating_get.return_value = [
            dict(test_floating_ip.fake_floating_ip,
                 interface='foo',
                 address='1.2.3.4'),
            dict(test_floating_ip.fake_floating_ip,
                 interface='fakeiface',
                 address='1.2.3.5',
                 fixed_ip_id=1),
            dict(test_floating_ip.fake_floating_ip,
                 interface='bar',
                 address='1.2.3.6',
                 fixed_ip_id=2),
            ]

        def fixed_ip_get(_context, fixed_ip_id, get_network):
            if fixed_ip_id == 1:
                return dict(test_fixed_ip.fake_fixed_ip,
                            address='1.2.3.4',
                            network=test_network.fake_network)
            raise exception.FixedIpNotFound(id=fixed_ip_id)
        fixed_get.side_effect = fixed_ip_get

        self.mox.StubOutWithMock(self.network.l3driver, 'add_floating_ip')
        self.flags(public_interface=public_interface)
        self.network.l3driver.add_floating_ip(netaddr.IPAddress('1.2.3.5'),
                                              netaddr.IPAddress('1.2.3.4'),
                                              expected_arg,
                                              mox.IsA(network_obj.Network))
        self.mox.ReplayAll()
        self.network.init_host_floating_ips()
        self.mox.UnsetStubs()
        self.mox.VerifyAll()

    def test_floating_ip_init_host_without_public_interface(self):
        self._test_floating_ip_init_host(public_interface=False,
                                         expected_arg='fakeiface')

    def test_floating_ip_init_host_with_public_interface(self):
        self._test_floating_ip_init_host(public_interface='fooiface',
                                         expected_arg='fooiface')

    def test_disassociate_floating_ip(self):
        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        def fake1(*args, **kwargs):
            pass

        # floating ip that isn't associated
        def fake2(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=None)

        # floating ip that is associated
        def fake3(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=1,
                        project_id=ctxt.project_id)

        # fixed ip with remote host
        def fake4(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=123)

        def fake4_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False,
                        host='jibberjabber')

        # fixed ip with local host
        def fake5(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        address='10.0.0.1',
                        pool='nova',
                        instance_uuid=FAKEUUID,
                        interface='eth0',
                        network_id=1234)

        def fake5_network(*args, **kwargs):
            return dict(test_network.fake_network,
                        multi_host=False, host='testhost')

        def fake6(ctxt, method, **kwargs):
            self.local = False

        def fake7(*args, **kwargs):
            self.local = True

        def fake8(*args, **kwargs):
            return dict(test_floating_ip.fake_floating_ip,
                        address='10.0.0.1',
                        pool='nova',
                        interface='eth0',
                        fixed_ip_id=1,
                        auto_assigned=True,
                        project_id=ctxt.project_id)

        self.stubs.Set(self.network, '_floating_ip_owned_by_project', fake1)

        # raises because floating_ip is not associated to a fixed_ip
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake2)
        self.assertRaises(exception.FloatingIpNotAssociated,
                          self.network.disassociate_floating_ip,
                          ctxt,
                          mox.IgnoreArg())

        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake3)

        # does not raise and makes call remotely
        self.local = True
        self.stubs.Set(self.network.db, 'fixed_ip_get', fake4)
        self.stubs.Set(self.network.db, 'network_get', fake4_network)
        self.stubs.Set(self.network.network_rpcapi.client, 'prepare',
                       lambda **kw: self.network.network_rpcapi.client)
        self.stubs.Set(self.network.network_rpcapi.client, 'call', fake6)
        self.network.disassociate_floating_ip(ctxt, mox.IgnoreArg())
        self.assertFalse(self.local)

        # does not raise and makes call locally
        self.local = False
        self.stubs.Set(self.network.db, 'fixed_ip_get', fake5)
        self.stubs.Set(self.network.db, 'network_get', fake5_network)
        self.stubs.Set(self.network, '_disassociate_floating_ip', fake7)
        self.network.disassociate_floating_ip(ctxt, mox.IgnoreArg())
        self.assertTrue(self.local)

        # raises because auto_assigned floating IP cannot be disassociated
        self.stubs.Set(self.network.db, 'floating_ip_get_by_address', fake8)
        self.assertRaises(exception.CannotDisassociateAutoAssignedFloatingIP,
                          self.network.disassociate_floating_ip,
                          ctxt,
                          mox.IgnoreArg())

    def test_add_fixed_ip_instance_without_vpn_requested_networks(self):
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                lambda *a, **kw: None)
        self.mox.StubOutWithMock(db, 'network_get')
        self.mox.StubOutWithMock(db, 'fixed_ip_associate_pool')
        self.mox.StubOutWithMock(db,
                              'virtual_interface_get_by_instance_and_network')
        self.mox.StubOutWithMock(db, 'fixed_ip_update')
        self.mox.StubOutWithMock(db, 'instance_get_by_uuid')
        self.mox.StubOutWithMock(self.network, 'get_instance_nw_info')

        db.fixed_ip_update(mox.IgnoreArg(),
                           mox.IgnoreArg(),
                           mox.IgnoreArg())
        db.virtual_interface_get_by_instance_and_network(mox.IgnoreArg(),
                mox.IgnoreArg(), mox.IgnoreArg()).AndReturn(vifs[0])

        fixed = dict(test_fixed_ip.fake_fixed_ip,
                     address='192.168.0.101')
        db.fixed_ip_associate_pool(mox.IgnoreArg(),
                                   mox.IgnoreArg(),
                                   instance_uuid=mox.IgnoreArg(),
                                   host=None).AndReturn(fixed)
        db.network_get(mox.IgnoreArg(),
                       mox.IgnoreArg(),
                       project_only=mox.IgnoreArg()
                       ).AndReturn(dict(test_network.fake_network,
                                        **networks[0]))
        db.instance_get_by_uuid(mox.IgnoreArg(),
                                mox.IgnoreArg(), use_slave=False,
                                columns_to_join=['info_cache',
                                                 'security_groups']
                                ).AndReturn(fake_inst(display_name=HOST,
                                                      uuid=FAKEUUID))
        self.network.get_instance_nw_info(mox.IgnoreArg(), mox.IgnoreArg(),
                                          mox.IgnoreArg(), mox.IgnoreArg())
        self.mox.ReplayAll()
        self.network.add_fixed_ip_to_instance(self.context, FAKEUUID, HOST,
                                              networks[0]['id'])

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    def test_ip_association_and_allocation_of_other_project(self, net_get,
                                                            fixed_get):
        """Makes sure that we cannot deallocaate or disassociate
        a public ip of other project.
        """
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])

        context1 = context.RequestContext('user', 'project1')
        context2 = context.RequestContext('user', 'project2')

        float_ip = db.floating_ip_create(context1.elevated(),
                                         {'address': '1.2.3.4',
                                          'project_id': context1.project_id})

        float_addr = float_ip['address']

        instance = db.instance_create(context1,
                                      {'project_id': 'project1'})

        fix_addr = db.fixed_ip_associate_pool(context1.elevated(),
                                              1, instance['uuid']).address
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr,
                                      instance_uuid=instance.uuid,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))

        # Associate the IP with non-admin user context
        self.assertRaises(exception.NotAuthorized,
                          self.network.associate_floating_ip,
                          context2,
                          float_addr,
                          fix_addr)

        # Deallocate address from other project
        self.assertRaises(exception.NotAuthorized,
                          self.network.deallocate_floating_ip,
                          context2,
                          float_addr)

        # Now Associates the address to the actual project
        self.network.associate_floating_ip(context1, float_addr, fix_addr)

        # Now try dis-associating from other project
        self.assertRaises(exception.NotAuthorized,
                          self.network.disassociate_floating_ip,
                          context2,
                          float_addr)

        # Clean up the ip addresses
        self.network.disassociate_floating_ip(context1, float_addr)
        self.network.deallocate_floating_ip(context1, float_addr)
        self.network.deallocate_fixed_ip(context1, fix_addr, 'fake')
        db.floating_ip_destroy(context1.elevated(), float_addr)
        db.fixed_ip_disassociate(context1.elevated(), fix_addr)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def test_deallocate_fixed(self, fixed_update, net_get, fixed_get):
        """Verify that release is called properly.

        Ensures https://bugs.launchpad.net/nova/+bug/973442 doesn't return
        """
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])

        def vif_get(_context, _vif_id):
            return vifs[0]

        self.stubs.Set(db, 'virtual_interface_get', vif_get)
        context1 = context.RequestContext('user', 'project1')

        instance = db.instance_create(context1,
                {'project_id': 'project1'})

        elevated = context1.elevated()
        fix_addr = db.fixed_ip_associate_pool(elevated, 1, instance['uuid'])
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr.address,
                                      instance_uuid=instance.uuid,
                                      allocated=True,
                                      virtual_interface_id=3,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))

        self.flags(force_dhcp_release=True)
        self.mox.StubOutWithMock(linux_net, 'release_dhcp')
        linux_net.release_dhcp(networks[1]['bridge'], fix_addr.address,
                'DE:AD:BE:EF:00:00')
        self.mox.ReplayAll()
        self.network.deallocate_fixed_ip(context1, fix_addr.address, 'fake')
        fixed_update.assert_called_once_with(context1, fix_addr.address,
                                             {'allocated': False,
                                              'virtual_interface_id': None})

    def test_deallocate_fixed_deleted(self):
        # Verify doesn't deallocate deleted fixed_ip from deleted network.

        def teardown_network_on_host(_context, network):
            if network['id'] == 0:
                raise test.TestingException()

        self.stubs.Set(self.network, '_teardown_network_on_host',
                       teardown_network_on_host)

        context1 = context.RequestContext('user', 'project1')
        elevated = context1.elevated()

        instance = db.instance_create(context1,
                {'project_id': 'project1'})
        network = db.network_create_safe(elevated, networks[0])

        _fix_addr = db.fixed_ip_associate_pool(elevated, 1, instance['uuid'])
        fix_addr = _fix_addr.address
        db.fixed_ip_update(elevated, fix_addr, {'deleted': 1})
        elevated.read_deleted = 'yes'
        delfixed = db.fixed_ip_get_by_address(elevated, fix_addr)
        values = {'address': fix_addr,
                  'network_id': network.id,
                  'instance_uuid': delfixed['instance_uuid']}
        db.fixed_ip_create(elevated, values)
        elevated.read_deleted = 'no'
        elevated.read_deleted = 'yes'

        deallocate = self.network.deallocate_fixed_ip
        self.assertRaises(test.TestingException, deallocate, context1,
                          fix_addr, 'fake')

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def test_deallocate_fixed_no_vif(self, fixed_update, net_get, fixed_get):
        """Verify that deallocate doesn't raise when no vif is returned.

        Ensures https://bugs.launchpad.net/nova/+bug/968457 doesn't return
        """
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])

        def vif_get(_context, _vif_id):
            return None

        self.stubs.Set(db, 'virtual_interface_get', vif_get)
        context1 = context.RequestContext('user', 'project1')

        instance = db.instance_create(context1,
                                      {'project_id': 'project1'})

        elevated = context1.elevated()
        fix_addr = db.fixed_ip_associate_pool(elevated, 1, instance['uuid'])
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr.address,
                                      allocated=True,
                                      virtual_interface_id=3,
                                      instance_uuid=instance.uuid,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))
        self.flags(force_dhcp_release=True)
        fixed_update.return_value = fixed_get.return_value
        self.network.deallocate_fixed_ip(context1, fix_addr.address, 'fake')
        fixed_update.assert_called_once_with(context1, fix_addr.address,
                                             {'allocated': False,
                                              'virtual_interface_id': None})

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ip_update')
    def test_fixed_ip_cleanup_fail(self, fixed_update, net_get, fixed_get):
        # Verify IP is not deallocated if the security group refresh fails.
        net_get.return_value = dict(test_network.fake_network,
                                    **networks[1])
        context1 = context.RequestContext('user', 'project1')

        instance = db.instance_create(context1,
                {'project_id': 'project1'})

        elevated = context1.elevated()
        fix_addr = fixed_ip_obj.FixedIP.associate_pool(elevated, 1,
                                                       instance['uuid'])

        def fake_refresh(instance_uuid):
            raise test.TestingException()
        self.stubs.Set(self.network,
                '_do_trigger_security_group_members_refresh_for_instance',
                fake_refresh)
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      address=fix_addr.address,
                                      allocated=True,
                                      virtual_interface_id=3,
                                      instance_uuid=instance.uuid,
                                      network=dict(test_network.fake_network,
                                                   **networks[1]))
        self.assertRaises(test.TestingException,
                          self.network.deallocate_fixed_ip,
                          context1, str(fix_addr.address), 'fake')
        self.assertFalse(fixed_update.called)

    def test_get_networks_by_uuids_ordering(self):
        self.mox.StubOutWithMock(db, 'network_get_all_by_uuids')

        requested_networks = ['bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb',
                              'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa']
        db.network_get_all_by_uuids(mox.IgnoreArg(), mox.IgnoreArg(),
                mox.IgnoreArg()).AndReturn(
                    [dict(test_network.fake_network, **net)
                     for net in networks])

        self.mox.ReplayAll()
        res = self.network._get_networks_by_uuids(self.context,
                                                  requested_networks)

        self.assertEqual(res[0]['id'], 1)
        self.assertEqual(res[1]['id'], 0)


class _TestDomainObject(object):
    def __init__(self, **kwargs):
        for k, v in kwargs.iteritems():
            self.__setattr__(k, v)


class FakeNetwork(object):
    def __init__(self, **kwargs):
        self.vlan = None
        for k, v in kwargs.iteritems():
            self.__setattr__(k, v)

    def __getitem__(self, item):
        return getattr(self, item)


class CommonNetworkTestCase(test.TestCase):

    def setUp(self):
        super(CommonNetworkTestCase, self).setUp()
        self.context = context.RequestContext('fake', 'fake')
        self.flags(ipv6_backend='rfc2462')
        self.flags(use_local=True, group='conductor')
        ipv6.reset_backend()

    def test_validate_instance_zone_for_dns_domain(self):
        domain = 'example.com'
        az = 'test_az'
        domains = {
            domain: _TestDomainObject(
                domain=domain,
                availability_zone=az)}

        def dnsdomain_get(context, instance_domain):
            return domains.get(instance_domain)

        self.stubs.Set(db, 'dnsdomain_get', dnsdomain_get)
        fake_instance = {'uuid': FAKEUUID,
                         'availability_zone': az}

        manager = network_manager.NetworkManager()
        res = manager._validate_instance_zone_for_dns_domain(self.context,
                                                             fake_instance)
        self.assertTrue(res)

    def fake_create_fixed_ips(self, context, network_id, fixed_cidr=None):
        return None

    def test_get_instance_nw_info_client_exceptions(self):
        manager = network_manager.NetworkManager()
        self.mox.StubOutWithMock(manager.db,
                                 'virtual_interface_get_by_instance')
        manager.db.virtual_interface_get_by_instance(
                self.context, FAKEUUID,
                use_slave=False).AndRaise(exception.InstanceNotFound(
                                                 instance_id=FAKEUUID))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          manager.get_instance_nw_info,
                          self.context, FAKEUUID, 'fake_rxtx_factor', HOST)

    @mock.patch('nova.db.instance_get')
    @mock.patch('nova.db.fixed_ip_get_by_instance')
    def test_deallocate_for_instance_passes_host_info(self, fixed_get,
                                                      instance_get):
        manager = fake_network.FakeNetworkManager()
        db = manager.db
        instance_get.return_value = fake_inst(uuid='ignoreduuid')
        db.virtual_interface_delete_by_instance = lambda _x, _y: None
        ctx = context.RequestContext('igonre', 'igonre')

        fixed_get.return_value = [dict(test_fixed_ip.fake_fixed_ip,
                                       address='1.2.3.4',
                                       network_id=123)]

        manager.deallocate_for_instance(
            ctx, instance=instance_obj.Instance._from_db_object(self.context,
                instance_obj.Instance(), instance_get.return_value))

        self.assertEqual([
            (ctx, '1.2.3.4', 'fake-host')
        ], manager.deallocate_fixed_ip_calls)

    @mock.patch('nova.db.fixed_ip_get_by_instance')
    @mock.patch('nova.db.fixed_ip_disassociate')
    def test_remove_fixed_ip_from_instance(self, disassociate, get):
        manager = fake_network.FakeNetworkManager()
        get.return_value = [
            dict(test_fixed_ip.fake_fixed_ip, **x)
            for x in manager.db.fixed_ip_get_by_instance(None,
                                                         FAKEUUID)]
        manager.remove_fixed_ip_from_instance(self.context, FAKEUUID,
                                              HOST,
                                              '10.0.0.1')

        self.assertEqual(manager.deallocate_called, '10.0.0.1')
        disassociate.assert_called_once_with(self.context, '10.0.0.1')

    @mock.patch('nova.db.fixed_ip_get_by_instance')
    def test_remove_fixed_ip_from_instance_bad_input(self, get):
        manager = fake_network.FakeNetworkManager()
        get.return_value = []
        self.assertRaises(exception.FixedIpNotFoundForSpecificInstance,
                          manager.remove_fixed_ip_from_instance,
                          self.context, 99, HOST, 'bad input')

    def test_validate_cidrs(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/24',
                                       False, 1, 256, None, None, None,
                                       None, None)
        self.assertEqual(1, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertIn('192.168.0.0/24', cidrs)

    def test_validate_cidrs_split_exact_in_half(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/24',
                                       False, 2, 128, None, None, None,
                                       None, None)
        self.assertEqual(2, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        self.assertIn('192.168.0.0/25', cidrs)
        self.assertIn('192.168.0.128/25', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_cidr_in_use_middle_of_range(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.2.0/24')]
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/16',
                                       False, 4, 256, None, None, None,
                                       None, None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertIn(exp_cidr, cidrs)
        self.assertNotIn('192.168.2.0/24', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_smaller_subnet_in_use(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.2.9/25')]
        # CidrConflict: requested cidr (192.168.2.0/24) conflicts with
        #               existing smaller cidr
        args = (self.context.elevated(), 'fake', '192.168.2.0/24', False,
                1, 256, None, None, None, None, None)
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_smaller_cidr_in_use(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.2.0/25')]
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/16',
                                       False, 4, 256, None, None, None, None,
                                       None)
        self.assertEqual(4, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.0.0/24', '192.168.1.0/24', '192.168.3.0/24',
                     '192.168.4.0/24']
        for exp_cidr in exp_cidrs:
            self.assertIn(exp_cidr, cidrs)
        self.assertNotIn('192.168.2.0/24', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_smaller_cidr_in_use2(self, get_all):
        manager = fake_network.FakeNetworkManager()
        self.mox.StubOutWithMock(manager.db, 'network_get_all')
        get_all.return_value = [dict(test_network.fake_network, id=1,
                                     cidr='192.168.2.9/29')]
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.2.0/24',
                                       False, 3, 32, None, None, None, None,
                                       None)
        self.assertEqual(3, len(nets))
        cidrs = [str(net['cidr']) for net in nets]
        exp_cidrs = ['192.168.2.32/27', '192.168.2.64/27', '192.168.2.96/27']
        for exp_cidr in exp_cidrs:
            self.assertIn(exp_cidr, cidrs)
        self.assertNotIn('192.168.2.0/27', cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_split_all_in_use(self, get_all):
        manager = fake_network.FakeNetworkManager()
        in_use = [dict(test_network.fake_network, **values) for values in
                  [{'id': 1, 'cidr': '192.168.2.9/29'},
                   {'id': 2, 'cidr': '192.168.2.64/26'},
                   {'id': 3, 'cidr': '192.168.2.128/26'}]]
        get_all.return_value = in_use
        args = (self.context.elevated(), 'fake', '192.168.2.0/24', False,
                3, 64, None, None, None, None, None)
        # CidrConflict: Not enough subnets avail to satisfy requested num_
        #               networks - some subnets in requested range already
        #               in use
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_validate_cidrs_one_in_use(self):
        manager = fake_network.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 2, 256, None, None,
                None, None, None)
        # ValueError: network_size * num_networks exceeds cidr size
        self.assertRaises(ValueError, manager.create_networks, *args)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_already_used(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     cidr='192.168.0.0/24')]
        # CidrConflict: cidr already in use
        args = (self.context.elevated(), 'fake', '192.168.0.0/24', False,
                1, 256, None, None, None, None, None)
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_validate_cidrs_too_many(self):
        manager = fake_network.FakeNetworkManager()
        args = (None, 'fake', '192.168.0.0/24', False, 200, 256, None, None,
                None, None, None)
        # ValueError: Not enough subnets avail to satisfy requested
        #             num_networks
        self.assertRaises(ValueError, manager.create_networks, *args)

    def test_validate_cidrs_split_partial(self):
        manager = fake_network.FakeNetworkManager()
        nets = manager.create_networks(self.context.elevated(), 'fake',
                                       '192.168.0.0/16',
                                       False, 2, 256, None, None, None, None,
                                       None)
        returned_cidrs = [str(net['cidr']) for net in nets]
        self.assertIn('192.168.0.0/24', returned_cidrs)
        self.assertIn('192.168.1.0/24', returned_cidrs)

    @mock.patch('nova.db.network_get_all')
    def test_validate_cidrs_conflict_existing_supernet(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.0.0/8')]
        args = (self.context.elevated(), 'fake', '192.168.0.0/24', False,
                1, 256, None, None, None, None, None)
        # CidrConflict: requested cidr (192.168.0.0/24) conflicts
        #               with existing supernet
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_create_networks(self):
        cidr = '192.168.0.0/24'
        manager = fake_network.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [self.context.elevated(), 'foo', cidr, None, 1, 256,
                'fd00::/48', None, None, None, None, None]
        self.assertTrue(manager.create_networks(*args))

    @mock.patch('nova.db.network_get_all')
    def test_create_networks_cidr_already_used(self, get_all):
        manager = fake_network.FakeNetworkManager()
        get_all.return_value = [dict(test_network.fake_network,
                                     id=1, cidr='192.168.0.0/24')]
        args = [self.context.elevated(), 'foo', '192.168.0.0/24', None, 1, 256,
                 'fd00::/48', None, None, None, None, None]
        self.assertRaises(exception.CidrConflict,
                          manager.create_networks, *args)

    def test_create_networks_many(self):
        cidr = '192.168.0.0/16'
        manager = fake_network.FakeNetworkManager()
        self.stubs.Set(manager, '_create_fixed_ips',
                                self.fake_create_fixed_ips)
        args = [self.context.elevated(), 'foo', cidr, None, 10, 256,
                'fd00::/48', None, None, None, None, None]
        self.assertTrue(manager.create_networks(*args))

    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ips_by_virtual_interface')
    def test_get_instance_uuids_by_ip_regex(self, fixed_get, network_get):
        manager = fake_network.FakeNetworkManager(self.stubs)
        fixed_get.side_effect = manager.db.fixed_ips_by_virtual_interface
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')
        network_get.return_value = dict(test_network.fake_network,
                                        **manager.db.network_get(None, 1))

        # Greedy get eveything
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '.*'})
        self.assertEqual(len(res), len(_vifs))

        # Doesn't exist
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '10.0.0.1'})
        self.assertFalse(res)

        # Get instance 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '172.16.0.2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_uuid'], _vifs[1]['instance_uuid'])

        # Get instance 2
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '173.16.0.2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_uuid'], _vifs[2]['instance_uuid'])

        # Get instance 0 and 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '172.16.0.*'})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_uuid'], _vifs[0]['instance_uuid'])
        self.assertEqual(res[1]['instance_uuid'], _vifs[1]['instance_uuid'])

        # Get instance 1 and 2
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip': '17..16.0.2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_uuid'], _vifs[1]['instance_uuid'])
        self.assertEqual(res[1]['instance_uuid'], _vifs[2]['instance_uuid'])

    @mock.patch('nova.db.network_get')
    def test_get_instance_uuids_by_ipv6_regex(self, network_get):
        manager = fake_network.FakeNetworkManager(self.stubs)
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')

        def _network_get(context, network_id, **args):
            return dict(test_network.fake_network,
                        **manager.db.network_get(context, network_id))
        network_get.side_effect = _network_get

        # Greedy get eveything
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*'})
        self.assertEqual(len(res), len(_vifs))

        # Doesn't exist
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*1034.*'})
        self.assertFalse(res)

        # Get instance 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '2001:.*2'})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_uuid'], _vifs[1]['instance_uuid'])

        # Get instance 2
        ip6 = '2001:db8:69:1f:dead:beff:feff:ef03'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': ip6})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_uuid'], _vifs[2]['instance_uuid'])

        # Get instance 0 and 1
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': '.*ef0[1,2]'})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_uuid'], _vifs[0]['instance_uuid'])
        self.assertEqual(res[1]['instance_uuid'], _vifs[1]['instance_uuid'])

        # Get instance 1 and 2
        ip6 = '2001:db8:69:1.:dead:beff:feff:ef0.'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'ip6': ip6})
        self.assertTrue(res)
        self.assertEqual(len(res), 2)
        self.assertEqual(res[0]['instance_uuid'], _vifs[1]['instance_uuid'])
        self.assertEqual(res[1]['instance_uuid'], _vifs[2]['instance_uuid'])

    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.fixed_ips_by_virtual_interface')
    def test_get_instance_uuids_by_ip(self, fixed_get, network_get):
        manager = fake_network.FakeNetworkManager(self.stubs)
        fixed_get.side_effect = manager.db.fixed_ips_by_virtual_interface
        _vifs = manager.db.virtual_interface_get_all(None)
        fake_context = context.RequestContext('user', 'project')
        network_get.return_value = dict(test_network.fake_network,
                                        **manager.db.network_get(None, 1))

        # No regex for you!
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': '.*'})
        self.assertFalse(res)

        # Doesn't exist
        ip = '10.0.0.1'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': ip})
        self.assertFalse(res)

        # Get instance 1
        ip = '172.16.0.2'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': ip})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_uuid'], _vifs[1]['instance_uuid'])

        # Get instance 2
        ip = '173.16.0.2'
        res = manager.get_instance_uuids_by_ip_filter(fake_context,
                                                      {'fixed_ip': ip})
        self.assertTrue(res)
        self.assertEqual(len(res), 1)
        self.assertEqual(res[0]['instance_uuid'], _vifs[2]['instance_uuid'])

    @mock.patch('nova.db.network_get_by_uuid')
    def test_get_network(self, get):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get.return_value = dict(test_network.fake_network, **networks[0])
        uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        network = manager.get_network(fake_context, uuid)
        self.assertEqual(network['uuid'], uuid)

    @mock.patch('nova.db.network_get_by_uuid')
    def test_get_network_not_found(self, get):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get.side_effect = exception.NetworkNotFoundForUUID(uuid='foo')
        uuid = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        self.assertRaises(exception.NetworkNotFound,
                          manager.get_network, fake_context, uuid)

    @mock.patch('nova.db.network_get_all')
    def test_get_all_networks(self, get_all):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get_all.return_value = [dict(test_network.fake_network, **net)
                                for net in networks]
        output = manager.get_all_networks(fake_context)
        self.assertEqual(len(networks), 2)
        self.assertEqual(output[0]['uuid'],
                         'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa')
        self.assertEqual(output[1]['uuid'],
                         'bbbbbbbb-bbbb-bbbb-bbbb-bbbbbbbbbbbb')

    @mock.patch('nova.db.network_get_by_uuid')
    @mock.patch('nova.db.network_disassociate')
    def test_disassociate_network(self, disassociate, get):
        manager = fake_network.FakeNetworkManager()
        disassociate.return_value = True
        fake_context = context.RequestContext('user', 'project')
        get.return_value = dict(test_network.fake_network,
                                **networks[0])
        uuid = 'aaaaaaaa-aaaa-aaaa-aaaa-aaaaaaaaaaaa'
        manager.disassociate_network(fake_context, uuid)

    @mock.patch('nova.db.network_get_by_uuid')
    def test_disassociate_network_not_found(self, get):
        manager = fake_network.FakeNetworkManager()
        fake_context = context.RequestContext('user', 'project')
        get.side_effect = exception.NetworkNotFoundForUUID(uuid='fake')
        uuid = 'eeeeeeee-eeee-eeee-eeee-eeeeeeeeeeee'
        self.assertRaises(exception.NetworkNotFound,
                          manager.disassociate_network, fake_context, uuid)

    def _test_init_host_dynamic_fixed_range(self, net_manager):
        self.flags(fake_network=True,
                   routing_source_ip='172.16.0.1',
                   metadata_host='172.16.0.1',
                   public_interface='eth1',
                   dmz_cidr=['10.0.3.0/24'])
        binary_name = linux_net.get_binary_name()

        # Stub out calls we don't want to really run, mock the db
        self.stubs.Set(linux_net.iptables_manager, '_apply', lambda: None)
        self.stubs.Set(floating_ips.FloatingIP, 'init_host_floating_ips',
                                                lambda *args: None)
        self.stubs.Set(net_manager.l3driver, 'initialize_gateway',
                                             lambda *args: None)
        self.mox.StubOutWithMock(db, 'network_get_all_by_host')
        fake_networks = [dict(test_network.fake_network, **n)
                         for n in networks]
        db.network_get_all_by_host(mox.IgnoreArg(),
                                   mox.IgnoreArg()
                                   ).MultipleTimes().AndReturn(fake_networks)
        self.mox.ReplayAll()

        net_manager.init_host()

        # Get the iptables rules that got created
        current_lines = []
        new_lines = linux_net.iptables_manager._modify_rules(current_lines,
                                       linux_net.iptables_manager.ipv4['nat'],
                                       table_name='nat')

        expected_lines = ['[0:0] -A %s-snat -s %s -d 0.0.0.0/0 '
                          '-j SNAT --to-source %s -o %s'
                          % (binary_name, networks[0]['cidr'],
                                          CONF.routing_source_ip,
                                          CONF.public_interface),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s/32 -j ACCEPT'
                          % (binary_name, networks[0]['cidr'],
                                          CONF.metadata_host),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -j ACCEPT'
                          % (binary_name, networks[0]['cidr'],
                                          CONF.dmz_cidr[0]),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -m conntrack ! '
                          '--ctstate DNAT -j ACCEPT' % (binary_name,
                                                        networks[0]['cidr'],
                                                        networks[0]['cidr']),
                          '[0:0] -A %s-snat -s %s -d 0.0.0.0/0 '
                          '-j SNAT --to-source %s -o %s'
                          % (binary_name, networks[1]['cidr'],
                                          CONF.routing_source_ip,
                                          CONF.public_interface),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s/32 -j ACCEPT'
                          % (binary_name, networks[1]['cidr'],
                                          CONF.metadata_host),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -j ACCEPT'
                          % (binary_name, networks[1]['cidr'],
                                          CONF.dmz_cidr[0]),
                          '[0:0] -A %s-POSTROUTING -s %s -d %s -m conntrack ! '
                          '--ctstate DNAT -j ACCEPT' % (binary_name,
                                                        networks[1]['cidr'],
                                                        networks[1]['cidr'])]

        # Compare the expected rules against the actual ones
        for line in expected_lines:
            self.assertIn(line, new_lines)

        # Add an additional network and ensure the rules get configured
        new_network = {'id': 2,
                       'uuid': 'cccccccc-cccc-cccc-cccc-cccccccc',
                       'label': 'test2',
                       'injected': False,
                       'multi_host': False,
                       'cidr': '192.168.2.0/24',
                       'cidr_v6': '2001:dba::/64',
                       'gateway_v6': '2001:dba::1',
                       'netmask_v6': '64',
                       'netmask': '255.255.255.0',
                       'bridge': 'fa1',
                       'bridge_interface': 'fake_fa1',
                       'gateway': '192.168.2.1',
                       'broadcast': '192.168.2.255',
                       'dns1': '192.168.2.1',
                       'dns2': '192.168.2.2',
                       'vlan': None,
                       'host': HOST,
                       'project_id': 'fake_project',
                       'vpn_public_address': '192.168.2.2',
                       'vpn_public_port': '22',
                       'vpn_private_address': '10.0.0.2'}
        new_network_obj = network_obj.Network._from_db_object(
            self.context, network_obj.Network(),
            dict(test_network.fake_network, **new_network))

        ctxt = context.get_admin_context()
        net_manager._setup_network_on_host(ctxt, new_network_obj)

        # Get the new iptables rules that got created from adding a new network
        current_lines = []
        new_lines = linux_net.iptables_manager._modify_rules(current_lines,
                                       linux_net.iptables_manager.ipv4['nat'],
                                       table_name='nat')

        # Add the new expected rules to the old ones
        expected_lines += ['[0:0] -A %s-snat -s %s -d 0.0.0.0/0 '
                           '-j SNAT --to-source %s -o %s'
                           % (binary_name, new_network['cidr'],
                                           CONF.routing_source_ip,
                                           CONF.public_interface),
                           '[0:0] -A %s-POSTROUTING -s %s -d %s/32 -j ACCEPT'
                           % (binary_name, new_network['cidr'],
                                           CONF.metadata_host),
                           '[0:0] -A %s-POSTROUTING -s %s -d %s -j ACCEPT'
                           % (binary_name, new_network['cidr'],
                                           CONF.dmz_cidr[0]),
                           '[0:0] -A %s-POSTROUTING -s %s -d %s -m conntrack '
                           '! --ctstate DNAT -j ACCEPT' % (binary_name,
                                                       new_network['cidr'],
                                                       new_network['cidr'])]

        # Compare the expected rules (with new network) against the actual ones
        for line in expected_lines:
            self.assertIn(line, new_lines)

    def test_flatdhcpmanager_dynamic_fixed_range(self):
        """Test FlatDHCPManager NAT rules for fixed_range."""
        # Set the network manager
        self.network = network_manager.FlatDHCPManager(host=HOST)
        self.network.db = db

        # Test new behavior:
        #     CONF.fixed_range is not set, defaults to None
        #     Determine networks to NAT based on lookup
        self._test_init_host_dynamic_fixed_range(self.network)

    def test_vlanmanager_dynamic_fixed_range(self):
        """Test VlanManager NAT rules for fixed_range."""
        # Set the network manager
        self.network = network_manager.VlanManager(host=HOST)
        self.network.db = db

        # Test new behavior:
        #     CONF.fixed_range is not set, defaults to None
        #     Determine networks to NAT based on lookup
        self._test_init_host_dynamic_fixed_range(self.network)


class TestRPCFixedManager(network_manager.RPCAllocateFixedIP,
        network_manager.NetworkManager):
    """Dummy manager that implements RPCAllocateFixedIP."""


class RPCAllocateTestCase(test.TestCase):
    """Tests nova.network.manager.RPCAllocateFixedIP."""
    def setUp(self):
        super(RPCAllocateTestCase, self).setUp()
        self.flags(use_local=True, group='conductor')
        self.rpc_fixed = TestRPCFixedManager()
        self.context = context.RequestContext('fake', 'fake')

    def test_rpc_allocate(self):
        """Test to verify bug 855030 doesn't resurface.

        Mekes sure _rpc_allocate_fixed_ip returns a value so the call
        returns properly and the greenpool completes.
        """
        address = '10.10.10.10'

        def fake_allocate(*args, **kwargs):
            return address

        def fake_network_get(*args, **kwargs):
            return test_network.fake_network

        self.stubs.Set(self.rpc_fixed, 'allocate_fixed_ip', fake_allocate)
        self.stubs.Set(self.rpc_fixed.db, 'network_get', fake_network_get)
        rval = self.rpc_fixed._rpc_allocate_fixed_ip(self.context,
                                                     'fake_instance',
                                                     'fake_network')
        self.assertEqual(rval, address)


class TestFloatingIPManager(floating_ips.FloatingIP,
        network_manager.NetworkManager):
    """Dummy manager that implements FloatingIP."""


class AllocateTestCase(test.TestCase):
    def setUp(self):
        super(AllocateTestCase, self).setUp()
        self.useFixture(test.SampleNetworks())
        self.conductor = self.start_service(
            'conductor', manager=CONF.conductor.manager)
        self.compute = self.start_service('compute')
        self.network = self.start_service('network')

        self.user_id = 'fake'
        self.project_id = 'fake'
        self.context = context.RequestContext(self.user_id,
                                              self.project_id,
                                              is_admin=True)

    def test_allocate_for_instance(self):
        address = "10.10.10.10"
        self.flags(auto_assign_floating_ip=True)

        db.floating_ip_create(self.context,
                              {'address': address,
                               'pool': 'nova'})
        inst = instance_obj.Instance()
        inst.host = self.compute.host
        inst.display_name = HOST
        inst.instance_type_id = 1
        inst.uuid = FAKEUUID
        inst.create(self.context)
        networks = db.network_get_all(self.context)
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': self.network.host})
        project_id = self.context.project_id
        nw_info = self.network.allocate_for_instance(self.context,
            instance_id=inst['id'], instance_uuid=inst['uuid'],
            host=inst['host'], vpn=None, rxtx_factor=3,
            project_id=project_id, macs=None)
        self.assertEqual(1, len(nw_info))
        fixed_ip = nw_info.fixed_ips()[0]['address']
        self.assertTrue(utils.is_valid_ipv4(fixed_ip))
        self.network.deallocate_for_instance(self.context,
                instance=inst)

    def test_allocate_for_instance_with_mac(self):
        available_macs = set(['ca:fe:de:ad:be:ef'])
        inst = db.instance_create(self.context, {'host': self.compute.host,
                                                 'display_name': HOST,
                                                 'instance_type_id': 1})
        networks = db.network_get_all(self.context)
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': self.network.host})
        project_id = self.context.project_id
        nw_info = self.network.allocate_for_instance(self.context,
            instance_id=inst['id'], instance_uuid=inst['uuid'],
            host=inst['host'], vpn=None, rxtx_factor=3,
            project_id=project_id, macs=available_macs)
        assigned_macs = [vif['address'] for vif in nw_info]
        self.assertEqual(1, len(assigned_macs))
        self.assertEqual(available_macs.pop(), assigned_macs[0])
        self.network.deallocate_for_instance(self.context,
                                             instance_id=inst['id'],
                                             host=self.network.host,
                                             project_id=project_id)

    def test_allocate_for_instance_not_enough_macs(self):
        available_macs = set()
        inst = db.instance_create(self.context, {'host': self.compute.host,
                                                 'display_name': HOST,
                                                 'instance_type_id': 1})
        networks = db.network_get_all(self.context)
        for network in networks:
            db.network_update(self.context, network['id'],
                              {'host': self.network.host})
        project_id = self.context.project_id
        self.assertRaises(exception.VirtualInterfaceCreateException,
                          self.network.allocate_for_instance, self.context,
                          instance_id=inst['id'], instance_uuid=inst['uuid'],
                          host=inst['host'], vpn=None, rxtx_factor=3,
                          project_id=project_id, macs=available_macs)


class FloatingIPTestCase(test.TestCase):
    """Tests nova.network.manager.FloatingIP."""
    def setUp(self):
        super(FloatingIPTestCase, self).setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.flags(log_dir=self.tempdir)
        self.flags(use_local=True, group='conductor')
        self.network = TestFloatingIPManager()
        self.network.db = db
        self.project_id = 'testproject'
        self.context = context.RequestContext('testuser', self.project_id,
            is_admin=False)

    @mock.patch('nova.db.fixed_ip_get')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.instance_get_by_uuid')
    @mock.patch('nova.db.service_get_by_host_and_topic')
    @mock.patch('nova.db.floating_ip_get_by_address')
    def test_disassociate_floating_ip_multi_host_calls(self, floating_get,
                                                       service_get,
                                                       inst_get, net_get,
                                                       fixed_get):
        floating_ip = dict(test_floating_ip.fake_floating_ip,
                           fixed_ip_id=12)

        fixed_ip = dict(test_fixed_ip.fake_fixed_ip,
                        network_id=None,
                        instance_uuid='instance-uuid')

        network = dict(test_network.fake_network,
                       multi_host=True)

        instance = dict(fake_instance.fake_db_instance(host='some-other-host'))

        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        self.stubs.Set(self.network,
                       '_floating_ip_owned_by_project',
                       lambda _x, _y: True)

        floating_get.return_value = floating_ip
        fixed_get.return_value = fixed_ip
        net_get.return_value = network
        inst_get.return_value = instance
        service_get.return_value = test_service.fake_service

        self.stubs.Set(self.network.servicegroup_api,
                       'service_is_up',
                       lambda _x: True)

        self.mox.StubOutWithMock(
            self.network.network_rpcapi, '_disassociate_floating_ip')

        self.network.network_rpcapi._disassociate_floating_ip(
            ctxt, 'fl_ip', mox.IgnoreArg(), 'some-other-host', 'instance-uuid')
        self.mox.ReplayAll()

        self.network.disassociate_floating_ip(ctxt, 'fl_ip', True)

    @mock.patch('nova.db.fixed_ip_get_by_address')
    @mock.patch('nova.db.network_get')
    @mock.patch('nova.db.instance_get_by_uuid')
    @mock.patch('nova.db.floating_ip_get_by_address')
    def test_associate_floating_ip_multi_host_calls(self, floating_get,
                                                    inst_get, net_get,
                                                    fixed_get):
        floating_ip = dict(test_floating_ip.fake_floating_ip,
                           fixed_ip_id=None)

        fixed_ip = dict(test_fixed_ip.fake_fixed_ip,
                        network_id=None,
                        instance_uuid='instance-uuid')

        network = dict(test_network.fake_network,
                       multi_host=True)

        instance = dict(fake_instance.fake_db_instance(host='some-other-host'))

        ctxt = context.RequestContext('testuser', 'testproject',
                                      is_admin=False)

        self.stubs.Set(self.network,
                       '_floating_ip_owned_by_project',
                       lambda _x, _y: True)

        floating_get.return_value = floating_ip
        fixed_get.return_value = fixed_ip
        net_get.return_value = network
        inst_get.return_value = instance

        self.mox.StubOutWithMock(
            self.network.network_rpcapi, '_associate_floating_ip')

        self.network.network_rpcapi._associate_floating_ip(
            ctxt, 'fl_ip', 'fix_ip', mox.IgnoreArg(), 'some-other-host',
            'instance-uuid')
        self.mox.ReplayAll()

        self.network.associate_floating_ip(ctxt, 'fl_ip', 'fix_ip', True)

    def test_double_deallocation(self):
        instance_ref = db.instance_create(self.context,
                {"project_id": self.project_id})
        # Run it twice to make it fault if it does not handle
        # instances without fixed networks
        # If this fails in either, it does not handle having no addresses
        self.network.deallocate_for_instance(self.context,
                instance_id=instance_ref['id'])
        self.network.deallocate_for_instance(self.context,
                instance_id=instance_ref['id'])

    def test_deallocation_deleted_instance(self):
        self.stubs.Set(self.network, '_teardown_network_on_host',
                       lambda *args, **kwargs: None)
        instance = instance_obj.Instance()
        instance.project_id = self.project_id
        instance.deleted = True
        instance.create(self.context)
        network = db.network_create_safe(self.context.elevated(), {
                'project_id': self.project_id,
                'host': CONF.host,
                'label': 'foo'})
        fixed = db.fixed_ip_create(self.context, {'allocated': True,
                'instance_uuid': instance.uuid, 'address': '10.1.1.1',
                'network_id': network['id']})
        db.floating_ip_create(self.context, {
                'address': '10.10.10.10', 'instance_uuid': instance.uuid,
                'fixed_ip_id': fixed['id'],
                'project_id': self.project_id})
        self.network.deallocate_for_instance(self.context, instance=instance)

    def test_deallocation_duplicate_floating_ip(self):
        self.stubs.Set(self.network, '_teardown_network_on_host',
                       lambda *args, **kwargs: None)
        instance = instance_obj.Instance()
        instance.project_id = self.project_id
        instance.create(self.context)
        network = db.network_create_safe(self.context.elevated(), {
                'project_id': self.project_id,
                'host': CONF.host,
                'label': 'foo'})
        fixed = db.fixed_ip_create(self.context, {'allocated': True,
                'instance_uuid': instance.uuid, 'address': '10.1.1.1',
                'network_id': network['id']})
        db.floating_ip_create(self.context, {
                'address': '10.10.10.10',
                'deleted': True})
        db.floating_ip_create(self.context, {
                'address': '10.10.10.10', 'instance_uuid': instance.uuid,
                'fixed_ip_id': fixed['id'],
                'project_id': self.project_id})
        self.network.deallocate_for_instance(self.context, instance=instance)

    @mock.patch('nova.db.fixed_ip_get')
    @mock.patch('nova.db.floating_ip_get_by_address')
    @mock.patch('nova.db.floating_ip_update')
    def test_migrate_instance_start(self, floating_update, floating_get,
                                    fixed_get):
        called = {'count': 0}

        def fake_floating_ip_get_by_address(context, address):
            return dict(test_floating_ip.fake_floating_ip,
                        address=address,
                        fixed_ip_id=0)

        def fake_is_stale_floating_ip_address(context, floating_ip):
            return str(floating_ip.address) == '172.24.4.23'

        floating_get.side_effect = fake_floating_ip_get_by_address
        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      instance_uuid='fake_uuid',
                                      address='10.0.0.2',
                                      network=test_network.fake_network)
        floating_update.return_value = fake_floating_ip_get_by_address(
            None, '1.2.3.4')

        def fake_remove_floating_ip(floating_addr, fixed_addr, interface,
                                    network):
            called['count'] += 1

        def fake_clean_conntrack(fixed_ip):
            if not str(fixed_ip) == "10.0.0.2":
                raise exception.FixedIpInvalid(address=fixed_ip)

        self.stubs.Set(self.network, '_is_stale_floating_ip_address',
                                 fake_is_stale_floating_ip_address)
        self.stubs.Set(self.network.l3driver, 'remove_floating_ip',
                       fake_remove_floating_ip)
        self.stubs.Set(self.network.l3driver, 'clean_conntrack',
                       fake_clean_conntrack)
        self.mox.ReplayAll()
        addresses = ['172.24.4.23', '172.24.4.24', '172.24.4.25']
        self.network.migrate_instance_start(self.context,
                                            instance_uuid=FAKEUUID,
                                            floating_addresses=addresses,
                                            rxtx_factor=3,
                                            project_id=self.project_id,
                                            source='fake_source',
                                            dest='fake_dest')

        self.assertEqual(called['count'], 2)

    @mock.patch('nova.db.fixed_ip_get')
    @mock.patch('nova.db.floating_ip_update')
    def test_migrate_instance_finish(self, floating_update, fixed_get):
        called = {'count': 0}

        def fake_floating_ip_get_by_address(context, address):
            return dict(test_floating_ip.fake_floating_ip,
                        address=address,
                        fixed_ip_id=0)

        def fake_is_stale_floating_ip_address(context, floating_ip):
            return str(floating_ip.address) == '172.24.4.23'

        fixed_get.return_value = dict(test_fixed_ip.fake_fixed_ip,
                                      instance_uuid='fake_uuid',
                                      address='10.0.0.2',
                                      network=test_network.fake_network)
        floating_update.return_value = fake_floating_ip_get_by_address(
            None, '1.2.3.4')

        def fake_add_floating_ip(floating_addr, fixed_addr, interface,
                                 network):
            called['count'] += 1

        self.stubs.Set(self.network.db, 'floating_ip_get_by_address',
                       fake_floating_ip_get_by_address)
        self.stubs.Set(self.network, '_is_stale_floating_ip_address',
                                 fake_is_stale_floating_ip_address)
        self.stubs.Set(self.network.l3driver, 'add_floating_ip',
                       fake_add_floating_ip)
        self.mox.ReplayAll()
        addresses = ['172.24.4.23', '172.24.4.24', '172.24.4.25']
        self.network.migrate_instance_finish(self.context,
                                             instance_uuid=FAKEUUID,
                                             floating_addresses=addresses,
                                             host='fake_dest',
                                             rxtx_factor=3,
                                             project_id=self.project_id,
                                             source='fake_source')

        self.assertEqual(called['count'], 2)

    def test_floating_dns_create_conflict(self):
        zone = "example.org"
        address1 = "10.10.10.11"
        name1 = "foo"

        self.network.add_dns_entry(self.context, address1, name1, "A", zone)

        self.assertRaises(exception.FloatingIpDNSExists,
                          self.network.add_dns_entry, self.context,
                          address1, name1, "A", zone)

    def test_floating_create_and_get(self):
        zone = "example.org"
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"
        entries = self.network.get_dns_entries_by_address(self.context,
                                                          address1, zone)
        self.assertFalse(entries)

        self.network.add_dns_entry(self.context, address1, name1, "A", zone)
        self.network.add_dns_entry(self.context, address1, name2, "A", zone)
        entries = self.network.get_dns_entries_by_address(self.context,
                                                          address1, zone)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0], name1)
        self.assertEqual(entries[1], name2)

        entries = self.network.get_dns_entries_by_name(self.context,
                                                       name1, zone)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], address1)

    def test_floating_dns_delete(self):
        zone = "example.org"
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"

        self.network.add_dns_entry(self.context, address1, name1, "A", zone)
        self.network.add_dns_entry(self.context, address1, name2, "A", zone)
        self.network.delete_dns_entry(self.context, name1, zone)

        entries = self.network.get_dns_entries_by_address(self.context,
                                                          address1, zone)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], name2)

        self.assertRaises(exception.NotFound,
                          self.network.delete_dns_entry, self.context,
                          name1, zone)

    def test_floating_dns_domains_public(self):
        zone1 = "testzone"
        domain1 = "example.org"
        domain2 = "example.com"
        address1 = '10.10.10.10'
        entryname = 'testentry'

        context_admin = context.RequestContext('testuser', 'testproject',
                                               is_admin=True)

        self.assertRaises(exception.AdminRequired,
                          self.network.create_public_dns_domain, self.context,
                          domain1, zone1)
        self.network.create_public_dns_domain(context_admin, domain1,
                                              'testproject')
        self.network.create_public_dns_domain(context_admin, domain2,
                                              'fakeproject')

        domains = self.network.get_dns_domains(self.context)
        self.assertEqual(len(domains), 2)
        self.assertEqual(domains[0]['domain'], domain1)
        self.assertEqual(domains[1]['domain'], domain2)
        self.assertEqual(domains[0]['project'], 'testproject')
        self.assertEqual(domains[1]['project'], 'fakeproject')

        self.network.add_dns_entry(self.context, address1, entryname,
                                   'A', domain1)
        entries = self.network.get_dns_entries_by_name(self.context,
                                                       entryname, domain1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], address1)

        self.assertRaises(exception.AdminRequired,
                          self.network.delete_dns_domain, self.context,
                          domain1)
        self.network.delete_dns_domain(context_admin, domain1)
        self.network.delete_dns_domain(context_admin, domain2)

        # Verify that deleting the domain deleted the associated entry
        entries = self.network.get_dns_entries_by_name(self.context,
                                                       entryname, domain1)
        self.assertFalse(entries)

    def test_delete_all_by_ip(self):
        domain1 = "example.org"
        domain2 = "example.com"
        address = "10.10.10.10"
        name1 = "foo"
        name2 = "bar"

        def fake_domains(context):
            return [{'domain': 'example.org', 'scope': 'public'},
                    {'domain': 'example.com', 'scope': 'public'},
                    {'domain': 'test.example.org', 'scope': 'public'}]

        self.stubs.Set(self.network, 'get_dns_domains', fake_domains)

        context_admin = context.RequestContext('testuser', 'testproject',
                                              is_admin=True)

        self.network.create_public_dns_domain(context_admin, domain1,
                                              'testproject')
        self.network.create_public_dns_domain(context_admin, domain2,
                                              'fakeproject')

        domains = self.network.get_dns_domains(self.context)
        for domain in domains:
            self.network.add_dns_entry(self.context, address,
                                       name1, "A", domain['domain'])
            self.network.add_dns_entry(self.context, address,
                                       name2, "A", domain['domain'])
            entries = self.network.get_dns_entries_by_address(self.context,
                                                              address,
                                                              domain['domain'])
            self.assertEqual(len(entries), 2)

        self.network._delete_all_entries_for_ip(self.context, address)

        for domain in domains:
            entries = self.network.get_dns_entries_by_address(self.context,
                                                              address,
                                                              domain['domain'])
            self.assertFalse(entries)

        self.network.delete_dns_domain(context_admin, domain1)
        self.network.delete_dns_domain(context_admin, domain2)

    def test_mac_conflicts(self):
        # Make sure MAC collisions are retried.
        self.flags(create_unique_mac_address_attempts=3)
        ctxt = context.RequestContext('testuser', 'testproject', is_admin=True)
        macs = ['bb:bb:bb:bb:bb:bb', 'aa:aa:aa:aa:aa:aa']

        # Create a VIF with aa:aa:aa:aa:aa:aa
        crash_test_dummy_vif = {
            'address': macs[1],
            'instance_uuid': 'fake_uuid',
            'network_id': 123,
            'uuid': 'fake_uuid',
            }
        self.network.db.virtual_interface_create(ctxt, crash_test_dummy_vif)

        # Hand out a collision first, then a legit MAC
        def fake_gen_mac():
            return macs.pop()
        self.stubs.Set(utils, 'generate_mac_address', fake_gen_mac)

        # SQLite doesn't seem to honor the uniqueness constraint on the
        # address column, so fake the collision-avoidance here
        def fake_vif_save(vif):
            if vif.address == crash_test_dummy_vif['address']:
                raise db_exc.DBError("If you're smart, you'll retry!")
            # NOTE(russellb) The VirtualInterface object requires an ID to be
            # set, and we expect it to get set automatically when we do the
            # save.
            vif.id = 1
        self.stubs.Set(models.VirtualInterface, 'save', fake_vif_save)

        # Attempt to add another and make sure that both MACs are consumed
        # by the retry loop
        self.network._add_virtual_interface(ctxt, 'fake_uuid', 123)
        self.assertEqual(macs, [])

    def test_deallocate_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get_by_address')
        self.network.db.floating_ip_get_by_address(
            self.context, '1.2.3.4').AndRaise(
                exception.FloatingIpNotFoundForAddress(address='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.deallocate_floating_ip,
                          self.context, '1.2.3.4')

    def test_associate_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get_by_address')
        self.network.db.floating_ip_get_by_address(
            self.context, '1.2.3.4').AndRaise(
                exception.FloatingIpNotFoundForAddress(address='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.associate_floating_ip,
                          self.context, '1.2.3.4', '10.0.0.1')

    def test_disassociate_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get_by_address')
        self.network.db.floating_ip_get_by_address(
            self.context, '1.2.3.4').AndRaise(
                exception.FloatingIpNotFoundForAddress(address='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.disassociate_floating_ip,
                          self.context, '1.2.3.4')

    def test_get_floating_ip_client_exceptions(self):
        # Ensure that FloatingIpNotFoundForAddress is wrapped.
        self.mox.StubOutWithMock(self.network.db, 'floating_ip_get')
        self.network.db.floating_ip_get(self.context, 'fake-id').AndRaise(
            exception.FloatingIpNotFound(id='fake'))
        self.mox.ReplayAll()
        self.assertRaises(messaging.ExpectedException,
                          self.network.get_floating_ip,
                          self.context, 'fake-id')

    def _test_associate_floating_ip_failure(self, stdout, expected_exception):
        def _fake_catchall(*args, **kwargs):
            return dict(test_fixed_ip.fake_fixed_ip,
                        network=test_network.fake_network)

        def _fake_add_floating_ip(*args, **kwargs):
            raise processutils.ProcessExecutionError(stdout)

        self.stubs.Set(self.network.db, 'floating_ip_fixed_ip_associate',
                _fake_catchall)
        self.stubs.Set(self.network.db, 'floating_ip_disassociate',
                _fake_catchall)
        self.stubs.Set(self.network.l3driver, 'add_floating_ip',
                _fake_add_floating_ip)

        self.assertRaises(expected_exception,
                          self.network._associate_floating_ip, self.context,
                          '1.2.3.4', '1.2.3.5', '', '')

    def test_associate_floating_ip_failure(self):
        self._test_associate_floating_ip_failure(None,
                processutils.ProcessExecutionError)

    def test_associate_floating_ip_failure_interface_not_found(self):
        self._test_associate_floating_ip_failure('Cannot find device',
                exception.NoFloatingIpInterface)


class InstanceDNSTestCase(test.TestCase):
    """Tests nova.network.manager instance DNS."""
    def setUp(self):
        super(InstanceDNSTestCase, self).setUp()
        self.tempdir = self.useFixture(fixtures.TempDir()).path
        self.flags(log_dir=self.tempdir)
        self.flags(use_local=True, group='conductor')
        self.network = TestFloatingIPManager()
        self.network.db = db
        self.project_id = 'testproject'
        self.context = context.RequestContext('testuser', self.project_id,
            is_admin=False)

    def test_dns_domains_private(self):
        zone1 = 'testzone'
        domain1 = 'example.org'

        context_admin = context.RequestContext('testuser', 'testproject',
                                              is_admin=True)

        self.assertRaises(exception.AdminRequired,
                          self.network.create_private_dns_domain, self.context,
                          domain1, zone1)

        self.network.create_private_dns_domain(context_admin, domain1, zone1)
        domains = self.network.get_dns_domains(self.context)
        self.assertEqual(len(domains), 1)
        self.assertEqual(domains[0]['domain'], domain1)
        self.assertEqual(domains[0]['availability_zone'], zone1)

        self.assertRaises(exception.AdminRequired,
                          self.network.delete_dns_domain, self.context,
                          domain1)
        self.network.delete_dns_domain(context_admin, domain1)


domain1 = "example.org"
domain2 = "example.com"


class LdapDNSTestCase(test.TestCase):
    """Tests nova.network.ldapdns.LdapDNS."""
    def setUp(self):
        super(LdapDNSTestCase, self).setUp()

        self.useFixture(test.ReplaceModule('ldap', fake_ldap))
        dns_class = 'nova.network.ldapdns.LdapDNS'
        self.driver = importutils.import_object(dns_class)

        attrs = {'objectClass': ['domainrelatedobject', 'dnsdomain',
                                 'domain', 'dcobject', 'top'],
                 'associateddomain': ['root'],
                 'dc': ['root']}
        self.driver.lobj.add_s("ou=hosts,dc=example,dc=org", attrs.items())
        self.driver.create_domain(domain1)
        self.driver.create_domain(domain2)

    def tearDown(self):
        self.driver.delete_domain(domain1)
        self.driver.delete_domain(domain2)
        super(LdapDNSTestCase, self).tearDown()

    def test_ldap_dns_domains(self):
        domains = self.driver.get_domains()
        self.assertEqual(len(domains), 2)
        self.assertIn(domain1, domains)
        self.assertIn(domain2, domains)

    def test_ldap_dns_create_conflict(self):
        address1 = "10.10.10.11"
        name1 = "foo"

        self.driver.create_entry(name1, address1, "A", domain1)

        self.assertRaises(exception.FloatingIpDNSExists,
                          self.driver.create_entry,
                          name1, address1, "A", domain1)

    def test_ldap_dns_create_and_get(self):
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"
        entries = self.driver.get_entries_by_address(address1, domain1)
        self.assertFalse(entries)

        self.driver.create_entry(name1, address1, "A", domain1)
        self.driver.create_entry(name2, address1, "A", domain1)
        entries = self.driver.get_entries_by_address(address1, domain1)
        self.assertEqual(len(entries), 2)
        self.assertEqual(entries[0], name1)
        self.assertEqual(entries[1], name2)

        entries = self.driver.get_entries_by_name(name1, domain1)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], address1)

    def test_ldap_dns_delete(self):
        address1 = "10.10.10.11"
        name1 = "foo"
        name2 = "bar"

        self.driver.create_entry(name1, address1, "A", domain1)
        self.driver.create_entry(name2, address1, "A", domain1)
        entries = self.driver.get_entries_by_address(address1, domain1)
        self.assertEqual(len(entries), 2)

        self.driver.delete_entry(name1, domain1)
        entries = self.driver.get_entries_by_address(address1, domain1)
        LOG.debug("entries: %s" % entries)
        self.assertEqual(len(entries), 1)
        self.assertEqual(entries[0], name2)

        self.assertRaises(exception.NotFound,
                          self.driver.delete_entry,
                          name1, domain1)
