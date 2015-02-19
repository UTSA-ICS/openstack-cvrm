# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2012 OpenStack Foundation
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

import mock

from neutron.agent.common import config
from neutron.agent.linux import dhcp
from neutron.agent.linux import interface
from neutron.agent.linux import ip_lib
from neutron.agent.linux import utils
from neutron.extensions.flavor import (FLAVOR_NETWORK)
from neutron.openstack.common import uuidutils
from neutron.tests import base


class BaseChild(interface.LinuxInterfaceDriver):
    def plug(*args):
        pass

    def unplug(*args):
        pass


class FakeNetwork:
    id = '12345678-1234-5678-90ab-ba0987654321'


class FakeSubnet:
    cidr = '192.168.1.1/24'


class FakeAllocation:
    subnet = FakeSubnet()
    ip_address = '192.168.1.2'
    ip_version = 4


class FakePort:
    id = 'abcdef01-1234-5678-90ab-ba0987654321'
    fixed_ips = [FakeAllocation]
    device_id = 'cccccccc-cccc-cccc-cccc-cccccccccccc'
    network = FakeNetwork()
    network_id = network.id


class TestBase(base.BaseTestCase):
    def setUp(self):
        super(TestBase, self).setUp()
        self.conf = config.setup_conf()
        self.conf.register_opts(interface.OPTS)
        config.register_root_helper(self.conf)
        self.ip_dev_p = mock.patch.object(ip_lib, 'IPDevice')
        self.ip_dev = self.ip_dev_p.start()
        self.addCleanup(self.ip_dev_p.stop)
        self.ip_p = mock.patch.object(ip_lib, 'IPWrapper')
        self.ip = self.ip_p.start()
        self.addCleanup(self.ip_p.stop)
        self.device_exists_p = mock.patch.object(ip_lib, 'device_exists')
        self.device_exists = self.device_exists_p.start()
        self.addCleanup(self.device_exists_p.stop)


class TestABCDriver(TestBase):
    def test_get_device_name(self):
        bc = BaseChild(self.conf)
        device_name = bc.get_device_name(FakePort())
        self.assertEqual('tapabcdef01-12', device_name)

    def test_l3_init(self):
        addresses = [dict(ip_version=4, scope='global',
                          dynamic=False, cidr='172.16.77.240/24')]
        self.ip_dev().addr.list = mock.Mock(return_value=addresses)

        bc = BaseChild(self.conf)
        ns = '12345678-1234-5678-90ab-ba0987654321'
        bc.init_l3('tap0', ['192.168.1.2/24'], namespace=ns)
        self.ip_dev.assert_has_calls(
            [mock.call('tap0', 'sudo', namespace=ns),
             mock.call().addr.list(scope='global', filters=['permanent']),
             mock.call().addr.add(4, '192.168.1.2/24', '192.168.1.255'),
             mock.call().addr.delete(4, '172.16.77.240/24')])

    def test_l3_init_with_preserve(self):
        addresses = [dict(ip_version=4, scope='global',
                          dynamic=False, cidr='192.168.1.3/32')]
        self.ip_dev().addr.list = mock.Mock(return_value=addresses)

        bc = BaseChild(self.conf)
        ns = '12345678-1234-5678-90ab-ba0987654321'
        bc.init_l3('tap0', ['192.168.1.2/24'], namespace=ns,
                   preserve_ips=['192.168.1.3/32'])
        self.ip_dev.assert_has_calls(
            [mock.call('tap0', 'sudo', namespace=ns),
             mock.call().addr.list(scope='global', filters=['permanent']),
             mock.call().addr.add(4, '192.168.1.2/24', '192.168.1.255')])
        self.assertFalse(self.ip_dev().addr.delete.called)


class TestOVSInterfaceDriver(TestBase):

    def test_get_device_name(self):
        br = interface.OVSInterfaceDriver(self.conf)
        device_name = br.get_device_name(FakePort())
        self.assertEqual('tapabcdef01-12', device_name)

    def test_plug_no_ns(self):
        self._test_plug()

    def test_plug_with_ns(self):
        self._test_plug(namespace='01234567-1234-1234-99')

    def test_plug_alt_bridge(self):
        self._test_plug(bridge='br-foo')

    def test_plug_configured_bridge(self):
        br = 'br-v'
        self.conf.set_override('ovs_use_veth', False)
        self.conf.set_override('ovs_integration_bridge', br)
        self.assertEqual(self.conf.ovs_integration_bridge, br)

        def device_exists(dev, root_helper=None, namespace=None):
            return dev == br

        ovs = interface.OVSInterfaceDriver(self.conf)
        with mock.patch.object(ovs, '_ovs_add_port') as add_port:
            self.device_exists.side_effect = device_exists
            ovs.plug('01234567-1234-1234-99',
                     'port-1234',
                     'tap0',
                     'aa:bb:cc:dd:ee:ff',
                     bridge=None,
                     namespace=None)

        add_port.assert_called_once_with('br-v',
                                         'tap0',
                                         'port-1234',
                                         'aa:bb:cc:dd:ee:ff',
                                         internal=True)

    def _test_plug(self, additional_expectation=[], bridge=None,
                   namespace=None):

        if not bridge:
            bridge = 'br-int'

        def device_exists(dev, root_helper=None, namespace=None):
            return dev == bridge

        vsctl_cmd = ['ovs-vsctl', '--', '--if-exists', 'del-port',
                     'tap0', '--', 'add-port',
                     bridge, 'tap0', '--', 'set', 'Interface', 'tap0',
                     'type=internal', '--', 'set', 'Interface', 'tap0',
                     'external-ids:iface-id=port-1234', '--', 'set',
                     'Interface', 'tap0',
                     'external-ids:iface-status=active', '--', 'set',
                     'Interface', 'tap0',
                     'external-ids:attached-mac=aa:bb:cc:dd:ee:ff']

        with mock.patch.object(utils, 'execute') as execute:
            ovs = interface.OVSInterfaceDriver(self.conf)
            self.device_exists.side_effect = device_exists
            ovs.plug('01234567-1234-1234-99',
                     'port-1234',
                     'tap0',
                     'aa:bb:cc:dd:ee:ff',
                     bridge=bridge,
                     namespace=namespace)
            execute.assert_called_once_with(vsctl_cmd, 'sudo')

        expected = [mock.call('sudo'),
                    mock.call().device('tap0'),
                    mock.call().device().link.set_address('aa:bb:cc:dd:ee:ff')]
        expected.extend(additional_expectation)
        if namespace:
            expected.extend(
                [mock.call().ensure_namespace(namespace),
                 mock.call().ensure_namespace().add_device_to_namespace(
                     mock.ANY)])
        expected.extend([mock.call().device().link.set_up()])

        self.ip.assert_has_calls(expected)

    def test_mtu_int(self):
        self.assertIsNone(self.conf.network_device_mtu)
        self.conf.set_override('network_device_mtu', 9000)
        self.assertEqual(self.conf.network_device_mtu, 9000)

    def test_plug_mtu(self):
        self.conf.set_override('network_device_mtu', 9000)
        self._test_plug([mock.call().device().link.set_mtu(9000)])

    def test_unplug(self, bridge=None):
        if not bridge:
            bridge = 'br-int'
        with mock.patch('neutron.agent.linux.ovs_lib.OVSBridge') as ovs_br:
            ovs = interface.OVSInterfaceDriver(self.conf)
            ovs.unplug('tap0')
            ovs_br.assert_has_calls([mock.call(bridge, 'sudo'),
                                     mock.call().delete_port('tap0')])


class TestOVSInterfaceDriverWithVeth(TestOVSInterfaceDriver):

    def setUp(self):
        super(TestOVSInterfaceDriverWithVeth, self).setUp()
        self.conf.set_override('ovs_use_veth', True)

    def test_get_device_name(self):
        br = interface.OVSInterfaceDriver(self.conf)
        device_name = br.get_device_name(FakePort())
        self.assertEqual('ns-abcdef01-12', device_name)

    def test_plug_with_prefix(self):
        self._test_plug(devname='qr-0', prefix='qr-')

    def _test_plug(self, devname=None, bridge=None, namespace=None,
                   prefix=None, mtu=None):

        if not devname:
            devname = 'ns-0'
        if not bridge:
            bridge = 'br-int'

        def device_exists(dev, root_helper=None, namespace=None):
            return dev == bridge

        ovs = interface.OVSInterfaceDriver(self.conf)
        self.device_exists.side_effect = device_exists

        root_dev = mock.Mock()
        ns_dev = mock.Mock()
        self.ip().add_veth = mock.Mock(return_value=(root_dev, ns_dev))
        expected = [mock.call('sudo'),
                    mock.call().add_veth('tap0', devname,
                                         namespace2=namespace)]

        vsctl_cmd = ['ovs-vsctl', '--', '--if-exists', 'del-port',
                     'tap0', '--', 'add-port',
                     bridge, 'tap0', '--', 'set', 'Interface', 'tap0',
                     'external-ids:iface-id=port-1234', '--', 'set',
                     'Interface', 'tap0',
                     'external-ids:iface-status=active', '--', 'set',
                     'Interface', 'tap0',
                     'external-ids:attached-mac=aa:bb:cc:dd:ee:ff']
        with mock.patch.object(utils, 'execute') as execute:
            ovs.plug('01234567-1234-1234-99',
                     'port-1234',
                     devname,
                     'aa:bb:cc:dd:ee:ff',
                     bridge=bridge,
                     namespace=namespace,
                     prefix=prefix)
            execute.assert_called_once_with(vsctl_cmd, 'sudo')

        ns_dev.assert_has_calls(
            [mock.call.link.set_address('aa:bb:cc:dd:ee:ff')])
        if mtu:
            ns_dev.assert_has_calls([mock.call.link.set_mtu(mtu)])
            root_dev.assert_has_calls([mock.call.link.set_mtu(mtu)])

        self.ip.assert_has_calls(expected)
        root_dev.assert_has_calls([mock.call.link.set_up()])
        ns_dev.assert_has_calls([mock.call.link.set_up()])

    def test_plug_mtu(self):
        self.conf.set_override('network_device_mtu', 9000)
        self._test_plug(mtu=9000)

    def test_unplug(self, bridge=None):
        if not bridge:
            bridge = 'br-int'
        with mock.patch('neutron.agent.linux.ovs_lib.OVSBridge') as ovs_br:
            ovs = interface.OVSInterfaceDriver(self.conf)
            ovs.unplug('ns-0', bridge=bridge)
            ovs_br.assert_has_calls([mock.call(bridge, 'sudo'),
                                     mock.call().delete_port('tap0')])
        self.ip_dev.assert_has_calls([mock.call('ns-0', 'sudo', None),
                                      mock.call().link.delete()])


class TestBridgeInterfaceDriver(TestBase):
    def test_get_device_name(self):
        br = interface.BridgeInterfaceDriver(self.conf)
        device_name = br.get_device_name(FakePort())
        self.assertEqual('ns-abcdef01-12', device_name)

    def test_plug_no_ns(self):
        self._test_plug()

    def test_plug_with_ns(self):
        self._test_plug(namespace='01234567-1234-1234-99')

    def _test_plug(self, namespace=None, mtu=None):
        def device_exists(device, root_helper=None, namespace=None):
            return device.startswith('brq')

        root_veth = mock.Mock()
        ns_veth = mock.Mock()

        self.ip().add_veth = mock.Mock(return_value=(root_veth, ns_veth))

        self.device_exists.side_effect = device_exists
        br = interface.BridgeInterfaceDriver(self.conf)
        mac_address = 'aa:bb:cc:dd:ee:ff'
        br.plug('01234567-1234-1234-99',
                'port-1234',
                'ns-0',
                mac_address,
                namespace=namespace)

        ip_calls = [mock.call('sudo'),
                    mock.call().add_veth('tap0', 'ns-0', namespace2=namespace)]
        ns_veth.assert_has_calls([mock.call.link.set_address(mac_address)])
        if mtu:
            ns_veth.assert_has_calls([mock.call.link.set_mtu(mtu)])
            root_veth.assert_has_calls([mock.call.link.set_mtu(mtu)])

        self.ip.assert_has_calls(ip_calls)

        root_veth.assert_has_calls([mock.call.link.set_up()])
        ns_veth.assert_has_calls([mock.call.link.set_up()])

    def test_plug_dev_exists(self):
        self.device_exists.return_value = True
        with mock.patch('neutron.agent.linux.interface.LOG.info') as log:
            br = interface.BridgeInterfaceDriver(self.conf)
            br.plug('01234567-1234-1234-99',
                    'port-1234',
                    'tap0',
                    'aa:bb:cc:dd:ee:ff')
            self.ip_dev.assert_has_calls([])
            self.assertEqual(log.call_count, 1)

    def test_plug_mtu(self):
        self.device_exists.return_value = False
        self.conf.set_override('network_device_mtu', 9000)
        self._test_plug(mtu=9000)

    def test_unplug_no_device(self):
        self.device_exists.return_value = False
        self.ip_dev().link.delete.side_effect = RuntimeError
        with mock.patch('neutron.agent.linux.interface.LOG') as log:
            br = interface.BridgeInterfaceDriver(self.conf)
            br.unplug('tap0')
            [mock.call(), mock.call('tap0', 'sudo'), mock.call().link.delete()]
            self.assertEqual(log.error.call_count, 1)

    def test_unplug(self):
        self.device_exists.return_value = True
        with mock.patch('neutron.agent.linux.interface.LOG.debug') as log:
            br = interface.BridgeInterfaceDriver(self.conf)
            br.unplug('tap0')
            log.assert_called_once()

        self.ip_dev.assert_has_calls([mock.call('tap0', 'sudo', None),
                                      mock.call().link.delete()])


class TestMetaInterfaceDriver(TestBase):
    def setUp(self):
        super(TestMetaInterfaceDriver, self).setUp()
        config.register_interface_driver_opts_helper(self.conf)
        self.conf.register_opts(dhcp.OPTS)
        self.client_cls_p = mock.patch('neutronclient.v2_0.client.Client')
        client_cls = self.client_cls_p.start()
        self.addCleanup(self.client_cls_p.stop)
        self.client_inst = mock.Mock()
        client_cls.return_value = self.client_inst

        fake_network = {'network': {FLAVOR_NETWORK: 'fake1'}}
        fake_port = {'ports':
                     [{'mac_address':
                      'aa:bb:cc:dd:ee:ffa', 'network_id': 'test'}]}

        self.client_inst.list_ports.return_value = fake_port
        self.client_inst.show_network.return_value = fake_network

        self.conf.set_override('auth_url', 'http://localhost:35357/v2.0')
        self.conf.set_override('auth_region', 'RegionOne')
        self.conf.set_override('admin_user', 'neutron')
        self.conf.set_override('admin_password', 'password')
        self.conf.set_override('admin_tenant_name', 'service')
        self.conf.set_override(
            'meta_flavor_driver_mappings',
            'fake1:neutron.agent.linux.interface.OVSInterfaceDriver,'
            'fake2:neutron.agent.linux.interface.BridgeInterfaceDriver')

    def test_get_driver_by_network_id(self):
        meta_interface = interface.MetaInterfaceDriver(self.conf)
        driver = meta_interface._get_driver_by_network_id('test')
        self.assertIsInstance(driver, interface.OVSInterfaceDriver)

    def test_set_device_plugin_tag(self):
        meta_interface = interface.MetaInterfaceDriver(self.conf)
        driver = meta_interface._get_driver_by_network_id('test')
        meta_interface._set_device_plugin_tag(driver,
                                              'tap0',
                                              namespace=None)
        expected = [mock.call('tap0', 'sudo', None),
                    mock.call().link.set_alias('fake1')]
        self.ip_dev.assert_has_calls(expected)
        namespace = '01234567-1234-1234-99'
        meta_interface._set_device_plugin_tag(driver,
                                              'tap1',
                                              namespace=namespace)
        expected = [mock.call('tap1', 'sudo', '01234567-1234-1234-99'),
                    mock.call().link.set_alias('fake1')]
        self.ip_dev.assert_has_calls(expected)

    def test_get_device_plugin_tag(self):
        meta_interface = interface.MetaInterfaceDriver(self.conf)
        self.ip_dev().link.alias = 'fake1'
        plugin_tag0 = meta_interface._get_device_plugin_tag('tap0',
                                                            namespace=None)
        expected = [mock.call('tap0', 'sudo', None)]
        self.ip_dev.assert_has_calls(expected)
        self.assertEqual('fake1', plugin_tag0)
        namespace = '01234567-1234-1234-99'
        expected = [mock.call('tap1', 'sudo', '01234567-1234-1234-99')]
        plugin_tag1 = meta_interface._get_device_plugin_tag(
            'tap1',
            namespace=namespace)
        self.ip_dev.assert_has_calls(expected)
        self.assertEqual('fake1', plugin_tag1)


class TestIVSInterfaceDriver(TestBase):

    def setUp(self):
        super(TestIVSInterfaceDriver, self).setUp()

    def test_get_device_name(self):
        br = interface.IVSInterfaceDriver(self.conf)
        device_name = br.get_device_name(FakePort())
        self.assertEqual('ns-abcdef01-12', device_name)

    def test_plug_with_prefix(self):
        self._test_plug(devname='qr-0', prefix='qr-')

    def _test_plug(self, devname=None, namespace=None,
                   prefix=None, mtu=None):

        if not devname:
            devname = 'ns-0'

        def device_exists(dev, root_helper=None, namespace=None):
            return dev == 'indigo'

        ivs = interface.IVSInterfaceDriver(self.conf)
        self.device_exists.side_effect = device_exists

        root_dev = mock.Mock()
        _ns_dev = mock.Mock()
        ns_dev = mock.Mock()
        self.ip().add_veth = mock.Mock(return_value=(root_dev, _ns_dev))
        self.ip().device = mock.Mock(return_value=(ns_dev))
        expected = [mock.call('sudo'), mock.call().add_veth('tap0', devname),
                    mock.call().device(devname)]

        ivsctl_cmd = ['ivs-ctl', 'add-port', 'tap0']

        with mock.patch.object(utils, 'execute') as execute:
            ivs.plug('01234567-1234-1234-99',
                     'port-1234',
                     devname,
                     'aa:bb:cc:dd:ee:ff',
                     namespace=namespace,
                     prefix=prefix)
            execute.assert_called_once_with(ivsctl_cmd, 'sudo')

        ns_dev.assert_has_calls(
            [mock.call.link.set_address('aa:bb:cc:dd:ee:ff')])
        if mtu:
            ns_dev.assert_has_calls([mock.call.link.set_mtu(mtu)])
            root_dev.assert_has_calls([mock.call.link.set_mtu(mtu)])
        if namespace:
            expected.extend(
                [mock.call().ensure_namespace(namespace),
                 mock.call().ensure_namespace().add_device_to_namespace(
                     mock.ANY)])

        self.ip.assert_has_calls(expected)
        root_dev.assert_has_calls([mock.call.link.set_up()])
        ns_dev.assert_has_calls([mock.call.link.set_up()])

    def test_plug_mtu(self):
        self.conf.set_override('network_device_mtu', 9000)
        self._test_plug(mtu=9000)

    def test_plug_namespace(self):
        self._test_plug(namespace='mynamespace')

    def test_unplug(self):
        ivs = interface.IVSInterfaceDriver(self.conf)
        ivsctl_cmd = ['ivs-ctl', 'del-port', 'tap0']
        with mock.patch.object(utils, 'execute') as execute:
            ivs.unplug('ns-0')
            execute.assert_called_once_with(ivsctl_cmd, 'sudo')
            self.ip_dev.assert_has_calls([mock.call('ns-0', 'sudo', None),
                                          mock.call().link.delete()])


class TestMidonetInterfaceDriver(TestBase):
    def setUp(self):
        self.conf = config.setup_conf()
        self.conf.register_opts(interface.OPTS)
        config.register_root_helper(self.conf)
        self.device_exists_p = mock.patch.object(ip_lib, 'device_exists')
        self.device_exists = self.device_exists_p.start()
        self.driver = interface.MidonetInterfaceDriver(self.conf)
        self.network_id = uuidutils.generate_uuid()
        self.port_id = uuidutils.generate_uuid()
        self.device_name = "tap0"
        self.mac_address = "aa:bb:cc:dd:ee:ff"
        self.bridge = "br-test"
        self.namespace = "ns-test"
        super(TestMidonetInterfaceDriver, self).setUp()

    def test_plug(self):
        cmd = ['mm-ctl', '--bind-port', self.port_id, 'tap0']
        self.device_exists.return_value = False

        root_dev = mock.Mock()
        ns_dev = mock.Mock()
        self.ip().add_veth = mock.Mock(return_value=(root_dev, ns_dev))
        with mock.patch.object(utils, 'execute') as execute:
            self.driver.plug(
                self.network_id, self.port_id,
                self.device_name, self.mac_address,
                self.bridge, self.namespace)
            execute.assert_called_once_with(cmd, 'sudo')

        expected = [mock.call(), mock.call('sudo'),
                    mock.call().add_veth(self.device_name,
                                         self.device_name,
                                         namespace2=self.namespace),
                    mock.call().ensure_namespace(self.namespace),
                    mock.call().ensure_namespace().add_device_to_namespace(
                        mock.ANY)]

        ns_dev.assert_has_calls(
            [mock.call.link.set_address(self.mac_address)])

        root_dev.assert_has_calls([mock.call.link.set_up()])
        ns_dev.assert_has_calls([mock.call.link.set_up()])
        self.ip.assert_has_calls(expected, True)

    def test_unplug(self):
        self.driver.unplug(self.device_name, self.bridge, self.namespace)

        self.ip_dev.assert_has_calls([
            mock.call(self.device_name, self.driver.root_helper,
                      self.namespace),
            mock.call().link.delete()])
        self.ip.assert_has_calls(mock.call().garbage_collect_namespace())
