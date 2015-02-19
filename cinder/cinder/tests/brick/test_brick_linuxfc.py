# (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import os.path
import string

from cinder.brick.initiator import linuxfc
from cinder.openstack.common import log as logging
from cinder import test

LOG = logging.getLogger(__name__)


class LinuxFCTestCase(test.TestCase):

    def setUp(self):
        super(LinuxFCTestCase, self).setUp()
        self.cmds = []
        self.stubs.Set(os.path, 'exists', lambda x: True)
        self.lfc = linuxfc.LinuxFibreChannel(None, execute=self.fake_execute)

    def fake_execute(self, *cmd, **kwargs):
        self.cmds.append(string.join(cmd))
        return "", None

    def test_rescan_hosts(self):
        hbas = [{'host_device': 'foo'},
                {'host_device': 'bar'}, ]
        self.lfc.rescan_hosts(hbas)
        expected_commands = ['tee -a /sys/class/scsi_host/foo/scan',
                             'tee -a /sys/class/scsi_host/bar/scan']
        self.assertEqual(expected_commands, self.cmds)

    def test_get_fc_hbas_fail(self):
        def fake_exec1(a, b, c, d, run_as_root=True, root_helper='sudo'):
            raise OSError

        def fake_exec2(a, b, c, d, run_as_root=True, root_helper='sudo'):
            return None, 'None found'

        self.stubs.Set(self.lfc, "_execute", fake_exec1)
        hbas = self.lfc.get_fc_hbas()
        self.assertEqual(0, len(hbas))
        self.stubs.Set(self.lfc, "_execute", fake_exec2)
        hbas = self.lfc.get_fc_hbas()
        self.assertEqual(0, len(hbas))

    def test_get_fc_hbas(self):
        def fake_exec(a, b, c, d, run_as_root=True, root_helper='sudo'):
            return SYSTOOL_FC, None
        self.stubs.Set(self.lfc, "_execute", fake_exec)
        hbas = self.lfc.get_fc_hbas()
        self.assertEqual(2, len(hbas))
        hba1 = hbas[0]
        self.assertEqual(hba1["ClassDevice"], "host0")
        hba2 = hbas[1]
        self.assertEqual(hba2["ClassDevice"], "host2")

    def test_get_fc_hbas_info(self):
        def fake_exec(a, b, c, d, run_as_root=True, root_helper='sudo'):
            return SYSTOOL_FC, None
        self.stubs.Set(self.lfc, "_execute", fake_exec)
        hbas_info = self.lfc.get_fc_hbas_info()
        expected_info = [{'device_path': '/sys/devices/pci0000:20/'
                                         '0000:20:03.0/0000:21:00.0/'
                                         'host0/fc_host/host0',
                          'host_device': 'host0',
                          'node_name': '50014380242b9751',
                          'port_name': '50014380242b9750'},
                         {'device_path': '/sys/devices/pci0000:20/'
                                         '0000:20:03.0/0000:21:00.1/'
                                         'host2/fc_host/host2',
                          'host_device': 'host2',
                          'node_name': '50014380242b9753',
                          'port_name': '50014380242b9752'}, ]
        self.assertEqual(expected_info, hbas_info)

    def test_get_fc_wwpns(self):
        def fake_exec(a, b, c, d, run_as_root=True, root_helper='sudo'):
            return SYSTOOL_FC, None
        self.stubs.Set(self.lfc, "_execute", fake_exec)
        wwpns = self.lfc.get_fc_wwpns()
        expected_wwpns = ['50014380242b9750', '50014380242b9752']
        self.assertEqual(expected_wwpns, wwpns)

    def test_get_fc_wwnns(self):
        def fake_exec(a, b, c, d, run_as_root=True, root_helper='sudo'):
            return SYSTOOL_FC, None
        self.stubs.Set(self.lfc, "_execute", fake_exec)
        wwnns = self.lfc.get_fc_wwpns()
        expected_wwnns = ['50014380242b9750', '50014380242b9752']
        self.assertEqual(expected_wwnns, wwnns)

SYSTOOL_FC = """
Class = "fc_host"

  Class Device = "host0"
  Class Device path = "/sys/devices/pci0000:20/0000:20:03.0/\
0000:21:00.0/host0/fc_host/host0"
    dev_loss_tmo        = "16"
    fabric_name         = "0x100000051ea338b9"
    issue_lip           = <store method only>
    max_npiv_vports     = "0"
    node_name           = "0x50014380242b9751"
    npiv_vports_inuse   = "0"
    port_id             = "0x960d0d"
    port_name           = "0x50014380242b9750"
    port_state          = "Online"
    port_type           = "NPort (fabric via point-to-point)"
    speed               = "8 Gbit"
    supported_classes   = "Class 3"
    supported_speeds    = "1 Gbit, 2 Gbit, 4 Gbit, 8 Gbit"
    symbolic_name       = "QMH2572 FW:v4.04.04 DVR:v8.03.07.12-k"
    system_hostname     = ""
    tgtid_bind_type     = "wwpn (World Wide Port Name)"
    uevent              =
    vport_create        = <store method only>
    vport_delete        = <store method only>

    Device = "host0"
    Device path = "/sys/devices/pci0000:20/0000:20:03.0/0000:21:00.0/host0"
      edc                 = <store method only>
      optrom_ctl          = <store method only>
      reset               = <store method only>
      uevent              = "DEVTYPE=scsi_host"


  Class Device = "host2"
  Class Device path = "/sys/devices/pci0000:20/0000:20:03.0/\
0000:21:00.1/host2/fc_host/host2"
    dev_loss_tmo        = "16"
    fabric_name         = "0x100000051ea33b79"
    issue_lip           = <store method only>
    max_npiv_vports     = "0"
    node_name           = "0x50014380242b9753"
    npiv_vports_inuse   = "0"
    port_id             = "0x970e09"
    port_name           = "0x50014380242b9752"
    port_state          = "Online"
    port_type           = "NPort (fabric via point-to-point)"
    speed               = "8 Gbit"
    supported_classes   = "Class 3"
    supported_speeds    = "1 Gbit, 2 Gbit, 4 Gbit, 8 Gbit"
    symbolic_name       = "QMH2572 FW:v4.04.04 DVR:v8.03.07.12-k"
    system_hostname     = ""
    tgtid_bind_type     = "wwpn (World Wide Port Name)"
    uevent              =
    vport_create        = <store method only>
    vport_delete        = <store method only>

    Device = "host2"
    Device path = "/sys/devices/pci0000:20/0000:20:03.0/0000:21:00.1/host2"
      edc                 = <store method only>
      optrom_ctl          = <store method only>
      reset               = <store method only>
      uevent              = "DEVTYPE=scsi_host"


"""
