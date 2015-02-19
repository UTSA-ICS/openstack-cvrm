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

"""Generic linux Fibre Channel utilities."""

import errno

from cinder.brick.initiator import linuxscsi
from cinder.openstack.common.gettextutils import _
from cinder.openstack.common import log as logging
from cinder.openstack.common import processutils as putils

LOG = logging.getLogger(__name__)


class LinuxFibreChannel(linuxscsi.LinuxSCSI):
    def __init__(self, root_helper, execute=putils.execute,
                 *args, **kwargs):
        super(LinuxFibreChannel, self).__init__(root_helper, execute,
                                                *args, **kwargs)

    def rescan_hosts(self, hbas):
        for hba in hbas:
            self.echo_scsi_command("/sys/class/scsi_host/%s/scan"
                                   % hba['host_device'], "- - -")

    def get_fc_hbas(self):
        """Get the Fibre Channel HBA information."""
        out = None
        try:
            out, err = self._execute('systool', '-c', 'fc_host', '-v',
                                     run_as_root=True,
                                     root_helper=self._root_helper)
        except putils.ProcessExecutionError as exc:
            # This handles the case where rootwrap is used
            # and systool is not installed
            # 96 = nova.cmd.rootwrap.RC_NOEXECFOUND:
            if exc.exit_code == 96:
                LOG.warn(_("systool is not installed"))
            return []
        except OSError as exc:
            # This handles the case where rootwrap is NOT used
            # and systool is not installed
            if exc.errno == errno.ENOENT:
                LOG.warn(_("systool is not installed"))
            return []

        # No FC HBAs were found
        if out is None:
            return []

        lines = out.split('\n')
        # ignore the first 2 lines
        lines = lines[2:]
        hbas = []
        hba = {}
        lastline = None
        for line in lines:
            line = line.strip()
            # 2 newlines denotes a new hba port
            if line == '' and lastline == '':
                if len(hba) > 0:
                    hbas.append(hba)
                    hba = {}
            else:
                val = line.split('=')
                if len(val) == 2:
                    key = val[0].strip().replace(" ", "")
                    value = val[1].strip()
                    hba[key] = value.replace('"', '')
            lastline = line

        return hbas

    def get_fc_hbas_info(self):
        """Get Fibre Channel WWNs and device paths from the system, if any."""

        # Note(walter-boring) modern Linux kernels contain the FC HBA's in /sys
        # and are obtainable via the systool app
        hbas = self.get_fc_hbas()
        if not hbas:
            return []

        hbas_info = []
        for hba in hbas:
            wwpn = hba['port_name'].replace('0x', '')
            wwnn = hba['node_name'].replace('0x', '')
            device_path = hba['ClassDevicepath']
            device = hba['ClassDevice']
            hbas_info.append({'port_name': wwpn,
                              'node_name': wwnn,
                              'host_device': device,
                              'device_path': device_path})
        return hbas_info

    def get_fc_wwpns(self):
        """Get Fibre Channel WWPNs from the system, if any."""

        # Note(walter-boring) modern Linux kernels contain the FC HBA's in /sys
        # and are obtainable via the systool app
        hbas = self.get_fc_hbas()

        wwpns = []
        if hbas:
            for hba in hbas:
                if hba['port_state'] == 'Online':
                    wwpn = hba['port_name'].replace('0x', '')
                    wwpns.append(wwpn)

        return wwpns

    def get_fc_wwnns(self):
        """Get Fibre Channel WWNNs from the system, if any."""

        # Note(walter-boring) modern Linux kernels contain the FC HBA's in /sys
        # and are obtainable via the systool app
        hbas = self.get_fc_hbas()
        if not hbas:
            return []

        wwnns = []
        if hbas:
            for hba in hbas:
                if hba['port_state'] == 'Online':
                    wwnn = hba['node_name'].replace('0x', '')
                    wwnns.append(wwnn)

        return wwnns
