# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2012 OpenStack Foundation.
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

import contextlib
import itertools
import mock

from neutron.agent.linux import ip_lib
from neutron.agent.linux import ovs_lib
from neutron.agent import ovs_cleanup_util as util
from neutron.openstack.common import uuidutils
from neutron.tests import base


class TestOVSCleanup(base.BaseTestCase):

    def test_setup_conf(self):
        conf = util.setup_conf()
        self.assertEqual(conf.external_network_bridge, 'br-ex')
        self.assertEqual(conf.ovs_integration_bridge, 'br-int')
        self.assertFalse(conf.ovs_all_ports)
        self.assertEqual(conf.AGENT.root_helper, 'sudo')

    def test_main(self):
        bridges = ['br-int', 'br-ex']
        ports = ['p1', 'p2', 'p3']
        conf = mock.Mock()
        conf.AGENT.root_helper = 'dummy_sudo'
        conf.ovs_all_ports = False
        conf.ovs_integration_bridge = 'br-int'
        conf.external_network_bridge = 'br-ex'
        with contextlib.nested(
            mock.patch('neutron.common.config.setup_logging'),
            mock.patch('neutron.agent.ovs_cleanup_util.setup_conf',
                       return_value=conf),
            mock.patch('neutron.agent.linux.ovs_lib.get_bridges',
                       return_value=bridges),
            mock.patch('neutron.agent.linux.ovs_lib.OVSBridge'),
            mock.patch.object(util, 'collect_neutron_ports',
                              return_value=ports),
            mock.patch.object(util, 'delete_neutron_ports')
        ) as (_log, _conf, _get, ovs, collect, delete):
            with mock.patch('neutron.common.config.setup_logging'):
                util.main()
                ovs.assert_has_calls([mock.call().delete_ports(
                    all_ports=False)])
                collect.assert_called_once_with(set(bridges), 'dummy_sudo')
                delete.assert_called_once_with(ports, 'dummy_sudo')

    def test_collect_neutron_ports(self):
        port1 = ovs_lib.VifPort('tap1234', 1, uuidutils.generate_uuid(),
                                '11:22:33:44:55:66', 'br')
        port2 = ovs_lib.VifPort('tap5678', 2, uuidutils.generate_uuid(),
                                '77:88:99:aa:bb:cc', 'br')
        port3 = ovs_lib.VifPort('tap90ab', 3, uuidutils.generate_uuid(),
                                '99:00:aa:bb:cc:dd', 'br')
        ports = [[port1, port2], [port3]]
        portnames = [p.port_name for p in itertools.chain(*ports)]
        with mock.patch('neutron.agent.linux.ovs_lib.OVSBridge') as ovs:
            ovs.return_value.get_vif_ports.side_effect = ports
            bridges = ['br-int', 'br-ex']
            ret = util.collect_neutron_ports(bridges, 'dummy_sudo')
            self.assertEqual(ret, portnames)

    def test_delete_neutron_ports(self):
        ports = ['tap1234', 'tap5678', 'tap09ab']
        port_found = [True, False, True]
        with contextlib.nested(
            mock.patch.object(ip_lib, 'device_exists',
                              side_effect=port_found),
            mock.patch.object(ip_lib, 'IPDevice')
        ) as (device_exists, ip_dev):
            util.delete_neutron_ports(ports, 'dummy_sudo')
            device_exists.assert_has_calls([mock.call(p) for p in ports])
            ip_dev.assert_has_calls(
                [mock.call('tap1234', 'dummy_sudo'),
                 mock.call().link.delete(),
                 mock.call('tap09ab', 'dummy_sudo'),
                 mock.call().link.delete()])
