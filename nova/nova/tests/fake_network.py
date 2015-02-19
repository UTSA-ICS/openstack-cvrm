# Copyright 2011 Rackspace
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

from oslo.config import cfg

from nova.compute import api as compute_api
from nova.compute import manager as compute_manager
import nova.context
from nova import db
from nova import exception
from nova.network import api as network_api
from nova.network import manager as network_manager
from nova.network import model as network_model
from nova.network import nova_ipam_lib
from nova.network import rpcapi as network_rpcapi
from nova.objects import base as obj_base
from nova.objects import instance_info_cache
from nova.objects import pci_device
from nova.objects import virtual_interface as vif_obj
from nova.openstack.common import jsonutils
from nova.tests.objects import test_fixed_ip
from nova.tests.objects import test_instance_info_cache
from nova.tests.objects import test_pci_device
from nova.virt.libvirt import config as libvirt_config


HOST = "testhost"
CONF = cfg.CONF
CONF.import_opt('use_ipv6', 'nova.netconf')


class FakeIptablesFirewallDriver(object):
    def __init__(self, **kwargs):
        pass

    def setattr(self, key, val):
        self.__setattr__(key, val)

    def apply_instance_filter(self, instance, network_info):
        pass


class FakeVIFDriver(object):

    def __init__(self, *args, **kwargs):
        pass

    def setattr(self, key, val):
        self.__setattr__(key, val)

    def get_config(self, instance, vif, image_meta, inst_type):
        conf = libvirt_config.LibvirtConfigGuestInterface()

        for attr, val in conf.__dict__.iteritems():
            if val is None:
                setattr(conf, attr, 'fake')

        return conf

    def plug(self, instance, vif):
        pass

    def unplug(self, instance, vif):
        pass


class FakeModel(dict):
    """Represent a model from the db."""
    def __init__(self, *args, **kwargs):
        self.update(kwargs)


class FakeNetworkManager(network_manager.NetworkManager):
    """This NetworkManager doesn't call the base class so we can bypass all
    inherited service cruft and just perform unit tests.
    """

    class FakeDB:
        vifs = [{'id': 0,
                 'created_at': None,
                 'updated_at': None,
                 'deleted_at': None,
                 'deleted': 0,
                 'instance_uuid': '00000000-0000-0000-0000-000000000010',
                 'network_id': 1,
                 'uuid': 'fake-uuid',
                 'address': 'DC:AD:BE:FF:EF:01'},
                {'id': 1,
                 'created_at': None,
                 'updated_at': None,
                 'deleted_at': None,
                 'deleted': 0,
                 'instance_uuid': '00000000-0000-0000-0000-000000000020',
                 'network_id': 21,
                 'uuid': 'fake-uuid2',
                 'address': 'DC:AD:BE:FF:EF:02'},
                {'id': 2,
                 'created_at': None,
                 'updated_at': None,
                 'deleted_at': None,
                 'deleted': 0,
                 'instance_uuid': '00000000-0000-0000-0000-000000000030',
                 'network_id': 31,
                 'uuid': 'fake-uuid3',
                 'address': 'DC:AD:BE:FF:EF:03'}]

        floating_ips = [dict(address='172.16.1.1',
                             fixed_ip_id=100),
                        dict(address='172.16.1.2',
                             fixed_ip_id=200),
                        dict(address='173.16.1.2',
                             fixed_ip_id=210)]

        fixed_ips = [dict(test_fixed_ip.fake_fixed_ip,
                          id=100,
                          address='172.16.0.1',
                          virtual_interface_id=0),
                     dict(test_fixed_ip.fake_fixed_ip,
                          id=200,
                          address='172.16.0.2',
                          virtual_interface_id=1),
                     dict(test_fixed_ip.fake_fixed_ip,
                          id=210,
                          address='173.16.0.2',
                          virtual_interface_id=2)]

        def fixed_ip_get_by_instance(self, context, instance_uuid):
            return [dict(address='10.0.0.0'), dict(address='10.0.0.1'),
                    dict(address='10.0.0.2')]

        def network_get_by_cidr(self, context, cidr):
            raise exception.NetworkNotFoundForCidr(cidr=cidr)

        def network_create_safe(self, context, net):
            fakenet = dict(net)
            fakenet['id'] = 999
            return fakenet

        def network_get(self, context, network_id, project_only="allow_none"):
            return {'cidr_v6': '2001:db8:69:%x::/64' % network_id}

        def network_get_by_uuid(self, context, network_uuid):
            raise exception.NetworkNotFoundForUUID(uuid=network_uuid)

        def network_get_all(self, context):
            raise exception.NoNetworksFound()

        def network_get_all_by_uuids(self, context, project_only="allow_none"):
            raise exception.NoNetworksFound()

        def network_disassociate(self, context, network_id):
            return True

        def virtual_interface_get_all(self, context):
            return self.vifs

        def fixed_ips_by_virtual_interface(self, context, vif_id):
            return [ip for ip in self.fixed_ips
                    if ip['virtual_interface_id'] == vif_id]

        def fixed_ip_disassociate(self, context, address):
            return True

    def __init__(self, stubs=None):
        self.db = self.FakeDB()
        if stubs:
            stubs.Set(vif_obj, 'db', self.db)
        self.deallocate_called = None
        self.deallocate_fixed_ip_calls = []
        self.network_rpcapi = network_rpcapi.NetworkAPI()

    # TODO(matelakat) method signature should align with the faked one's
    def deallocate_fixed_ip(self, context, address=None, host=None,
            instance=None):
        self.deallocate_fixed_ip_calls.append((context, address, host))
        # TODO(matelakat) use the deallocate_fixed_ip_calls instead
        self.deallocate_called = address

    def _create_fixed_ips(self, context, network_id, fixed_cidr=None):
        pass

    def get_instance_nw_info(context, instance_id, rxtx_factor,
                             host, instance_uuid=None, **kwargs):
        pass


def fake_network(network_id, ipv6=None):
    if ipv6 is None:
        ipv6 = CONF.use_ipv6
    fake_network = {'id': network_id,
             'uuid': '00000000-0000-0000-0000-00000000000000%02d' % network_id,
             'label': 'test%d' % network_id,
             'injected': False,
             'multi_host': False,
             'cidr': '192.168.%d.0/24' % network_id,
             'cidr_v6': None,
             'netmask': '255.255.255.0',
             'netmask_v6': None,
             'bridge': 'fake_br%d' % network_id,
             'bridge_interface': 'fake_eth%d' % network_id,
             'gateway': '192.168.%d.1' % network_id,
             'gateway_v6': None,
             'broadcast': '192.168.%d.255' % network_id,
             'dns1': '192.168.%d.3' % network_id,
             'dns2': '192.168.%d.4' % network_id,
             'dns3': '192.168.%d.3' % network_id,
             'vlan': None,
             'host': None,
             'project_id': 'fake_project',
             'vpn_public_address': '192.168.%d.2' % network_id,
             'vpn_public_port': None,
             'vpn_private_address': None,
             'dhcp_start': None,
             'rxtx_base': network_id * 10,
             'priority': None,
             'deleted': False,
             'created_at': None,
             'updated_at': None,
             'deleted_at': None}
    if ipv6:
        fake_network['cidr_v6'] = '2001:db8:0:%x::/64' % network_id
        fake_network['gateway_v6'] = '2001:db8:0:%x::1' % network_id
        fake_network['netmask_v6'] = '64'
    if CONF.flat_injected:
        fake_network['injected'] = True

    return fake_network


def vifs(n):
    for x in xrange(1, n + 1):
        yield {'id': x,
               'created_at': None,
               'updated_at': None,
               'deleted_at': None,
               'deleted': 0,
               'address': 'DE:AD:BE:EF:00:%02x' % x,
               'uuid': '00000000-0000-0000-0000-00000000000000%02d' % x,
               'network_id': x,
               'instance_uuid': 'fake-uuid'}


def floating_ip_ids():
    for i in xrange(1, 100):
        yield i


def fixed_ip_ids():
    for i in xrange(1, 100):
        yield i


floating_ip_id = floating_ip_ids()
fixed_ip_id = fixed_ip_ids()


def next_fixed_ip(network_id, num_floating_ips=0):
    next_id = fixed_ip_id.next()
    f_ips = [FakeModel(**next_floating_ip(next_id))
             for i in xrange(num_floating_ips)]
    return {'id': next_id,
            'network_id': network_id,
            'address': '192.168.%d.%03d' % (network_id, (next_id + 99)),
            'instance_uuid': 1,
            'allocated': False,
            # and since network_id and vif_id happen to be equivalent
            'virtual_interface_id': network_id,
            'floating_ips': f_ips}


def next_floating_ip(fixed_ip_id):
    next_id = floating_ip_id.next()
    return {'id': next_id,
            'address': '10.10.10.%03d' % (next_id + 99),
            'fixed_ip_id': fixed_ip_id,
            'project_id': None,
            'auto_assigned': False}


def ipv4_like(ip, match_string):
    ip = ip.split('.')
    match_octets = match_string.split('.')

    for i, octet in enumerate(match_octets):
        if octet == '*':
            continue
        if octet != ip[i]:
            return False
    return True


def fake_get_instance_nw_info(stubs, num_networks=1, ips_per_vif=2,
                              floating_ips_per_fixed_ip=0):
    # stubs is the self.stubs from the test
    # ips_per_vif is the number of ips each vif will have
    # num_floating_ips is number of float ips for each fixed ip
    network = network_manager.FlatManager(host=HOST)
    network.db = db

    # reset the fixed and floating ip generators
    global floating_ip_id, fixed_ip_id, fixed_ips
    floating_ip_id = floating_ip_ids()
    fixed_ip_id = fixed_ip_ids()
    fixed_ips = []

    networks = [fake_network(x) for x in xrange(1, num_networks + 1)]

    def fixed_ips_fake(*args, **kwargs):
        global fixed_ips
        ips = [next_fixed_ip(i, floating_ips_per_fixed_ip)
               for i in xrange(1, num_networks + 1)
               for j in xrange(ips_per_vif)]
        fixed_ips = ips
        return ips

    def floating_ips_fake(context, address):
        for ip in fixed_ips:
            if address == ip['address']:
                return ip['floating_ips']
        return []

    def fixed_ips_v6_fake():
        return ['2001:db8:0:%x::1' % i
                for i in xrange(1, num_networks + 1)]

    def virtual_interfaces_fake(*args, **kwargs):
        return [vif for vif in vifs(num_networks)]

    def vif_by_uuid_fake(context, uuid):
        return {'id': 1,
               'address': 'DE:AD:BE:EF:00:01',
               'uuid': uuid,
               'network_id': 1,
               'network': None,
               'instance_uuid': 'fake-uuid'}

    def network_get_fake(context, network_id, project_only='allow_none'):
        nets = [n for n in networks if n['id'] == network_id]
        if not nets:
            raise exception.NetworkNotFound(network_id=network_id)
        return nets[0]

    def update_cache_fake(*args, **kwargs):
        pass

    def get_subnets_by_net_id(self, context, project_id, network_uuid,
                              vif_uuid):
        i = int(network_uuid[-2:])
        subnet_v4 = dict(
            cidr='192.168.%d.0/24' % i,
            dns1='192.168.%d.3' % i,
            dns2='192.168.%d.4' % i,
            gateway='192.168.%d.1' % i)

        subnet_v6 = dict(
            cidr='2001:db8:0:%x::/64' % i,
            gateway='2001:db8:0:%x::1' % i)
        return [subnet_v4, subnet_v6]

    def get_network_by_uuid(context, uuid):
        return dict(id=1,
                    cidr_v6='fe80::/64',
                    bridge='br0',
                    label='public')

    def get_v4_fake(*args, **kwargs):
        ips = fixed_ips_fake(*args, **kwargs)
        return [ip['address'] for ip in ips]

    def get_v6_fake(*args, **kwargs):
        return fixed_ips_v6_fake()

    stubs.Set(db, 'fixed_ip_get_by_instance', fixed_ips_fake)
    stubs.Set(db, 'floating_ip_get_by_fixed_address', floating_ips_fake)
    stubs.Set(db, 'virtual_interface_get_by_uuid', vif_by_uuid_fake)
    stubs.Set(db, 'network_get_by_uuid', get_network_by_uuid)
    stubs.Set(db, 'virtual_interface_get_by_instance', virtual_interfaces_fake)
    stubs.Set(db, 'network_get', network_get_fake)
    stubs.Set(db, 'instance_info_cache_update', update_cache_fake)

    stubs.Set(nova_ipam_lib.NeutronNovaIPAMLib, 'get_subnets_by_net_id',
              get_subnets_by_net_id)
    stubs.Set(nova_ipam_lib.NeutronNovaIPAMLib, 'get_v4_ips_by_interface',
                    get_v4_fake)
    stubs.Set(nova_ipam_lib.NeutronNovaIPAMLib, 'get_v6_ips_by_interface',
                    get_v6_fake)

    class FakeContext(nova.context.RequestContext):
        def is_admin(self):
            return True

    nw_model = network.get_instance_nw_info(
                FakeContext('fakeuser', 'fake_project'),
                0, 3, None)
    return nw_model


def stub_out_nw_api_get_instance_nw_info(stubs, func=None,
                                         num_networks=1,
                                         ips_per_vif=1,
                                         floating_ips_per_fixed_ip=0):

    def get_instance_nw_info(self, context, instance, conductor_api=None):
        return fake_get_instance_nw_info(stubs, num_networks=num_networks,
                        ips_per_vif=ips_per_vif,
                        floating_ips_per_fixed_ip=floating_ips_per_fixed_ip)

    if func is None:
        func = get_instance_nw_info
    stubs.Set(network_api.API, 'get_instance_nw_info', func)


def stub_out_network_cleanup(stubs):
    stubs.Set(network_api.API, 'deallocate_for_instance',
              lambda *args, **kwargs: None)


_real_functions = {}


def set_stub_network_methods(stubs):
    global _real_functions
    cm = compute_manager.ComputeManager
    if not _real_functions:
        _real_functions = {
                '_get_instance_nw_info': cm._get_instance_nw_info,
                '_allocate_network': cm._allocate_network,
                '_deallocate_network': cm._deallocate_network}

    def fake_networkinfo(*args, **kwargs):
        return network_model.NetworkInfo()

    def fake_async_networkinfo(*args, **kwargs):
        return network_model.NetworkInfoAsyncWrapper(fake_networkinfo)

    stubs.Set(cm, '_get_instance_nw_info', fake_networkinfo)
    stubs.Set(cm, '_allocate_network', fake_async_networkinfo)
    stubs.Set(cm, '_deallocate_network', lambda *args, **kwargs: None)


def unset_stub_network_methods(stubs):
    global _real_functions
    if _real_functions:
        cm = compute_manager.ComputeManager
        for name in _real_functions:
            stubs.Set(cm, name, _real_functions[name])


def stub_compute_with_ips(stubs):
    orig_get = compute_api.API.get
    orig_get_all = compute_api.API.get_all
    orig_create = compute_api.API.create

    def fake_get(*args, **kwargs):
        return _get_instances_with_cached_ips(orig_get, *args, **kwargs)

    def fake_get_all(*args, **kwargs):
        return _get_instances_with_cached_ips(orig_get_all, *args, **kwargs)

    def fake_create(*args, **kwargs):
        return _create_instances_with_cached_ips(orig_create, *args, **kwargs)

    def fake_pci_device_get_by_addr(context, node_id, dev_addr):
        return test_pci_device.fake_db_dev

    stubs.Set(db, 'pci_device_get_by_addr', fake_pci_device_get_by_addr)
    stubs.Set(compute_api.API, 'get', fake_get)
    stubs.Set(compute_api.API, 'get_all', fake_get_all)
    stubs.Set(compute_api.API, 'create', fake_create)


def _get_fake_cache():
    def _ip(ip, fixed=True, floats=None):
        ip_dict = {'address': ip, 'type': 'fixed'}
        if not fixed:
            ip_dict['type'] = 'floating'
        if fixed and floats:
            ip_dict['floating_ips'] = [_ip(f, fixed=False) for f in floats]
        return ip_dict

    info = [{'address': 'aa:bb:cc:dd:ee:ff',
             'id': 1,
             'network': {'bridge': 'br0',
                         'id': 1,
                         'label': 'private',
                         'subnets': [{'cidr': '192.168.0.0/24',
                                      'ips': [_ip('192.168.0.3')]}]}}]
    if CONF.use_ipv6:
        ipv6_addr = 'fe80:b33f::a8bb:ccff:fedd:eeff'
        info[0]['network']['subnets'].append({'cidr': 'fe80:b33f::/64',
                                              'ips': [_ip(ipv6_addr)]})
    return jsonutils.dumps(info)


def _get_instances_with_cached_ips(orig_func, *args, **kwargs):
    """Kludge the cache into instance(s) without having to create DB
    entries
    """
    instances = orig_func(*args, **kwargs)
    context = args[0]
    fake_device = pci_device.PciDevice.get_by_dev_addr(context, 1, 'a')

    def _info_cache_for(instance):
        info_cache = dict(test_instance_info_cache.fake_info_cache,
                          network_info=_get_fake_cache(),
                          instance_uuid=instance['uuid'])
        if isinstance(instance, obj_base.NovaObject):
            _info_cache = instance_info_cache.InstanceInfoCache()
            instance_info_cache.InstanceInfoCache._from_db_object(context,
                                                                  _info_cache,
                                                                  info_cache)
            info_cache = _info_cache
        instance['info_cache'] = info_cache

    if isinstance(instances, (list, obj_base.ObjectListBase)):
        for instance in instances:
            _info_cache_for(instance)
            fake_device.claim(instance)
            fake_device.allocate(instance)
    else:
        _info_cache_for(instances)
        fake_device.claim(instances)
        fake_device.allocate(instances)
    return instances


def _create_instances_with_cached_ips(orig_func, *args, **kwargs):
    """Kludge the above kludge so that the database doesn't get out
    of sync with the actual instance.
    """
    instances, reservation_id = orig_func(*args, **kwargs)
    fake_cache = _get_fake_cache()
    for instance in instances:
        instance['info_cache']['network_info'] = fake_cache
        db.instance_info_cache_update(args[1], instance['uuid'],
                                      {'network_info': fake_cache})
    return (instances, reservation_id)
