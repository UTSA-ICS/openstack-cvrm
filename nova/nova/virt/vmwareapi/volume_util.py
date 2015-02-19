# Copyright (c) 2012 VMware, Inc.
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
Helper methods for operations related to the management of volumes,
and storage repositories
"""

from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)


class StorageError(Exception):
    """To raise errors related to Volume commands."""

    def __init__(self, message=None):
        super(StorageError, self).__init__(message)


def get_host_iqn(session, cluster=None):
    """Return the host iSCSI IQN."""
    host_mor = vm_util.get_host_ref(session, cluster)
    hbas_ret = session._call_method(vim_util, "get_dynamic_property",
                                    host_mor, "HostSystem",
                                    "config.storageDevice.hostBusAdapter")

    # Meaning there are no host bus adapters on the host
    if hbas_ret is None:
        return
    host_hbas = hbas_ret.HostHostBusAdapter
    if not host_hbas:
        return
    for hba in host_hbas:
        if hba.__class__.__name__ == 'HostInternetScsiHba':
            return hba.iScsiName


def find_st(session, data, cluster=None):
    """Return the iSCSI Target given a volume info."""
    target_portal = data['target_portal']
    target_iqn = data['target_iqn']
    host_mor = vm_util.get_host_ref(session, cluster)

    lst_properties = ["config.storageDevice.hostBusAdapter",
                      "config.storageDevice.scsiTopology",
                      "config.storageDevice.scsiLun"]
    prop_dict = session._call_method(vim_util, "get_dynamic_properties",
                       host_mor, "HostSystem", lst_properties)
    result = (None, None)
    hbas_ret = None
    scsi_topology = None
    scsi_lun_ret = None
    if prop_dict:
        hbas_ret = prop_dict.get('config.storageDevice.hostBusAdapter')
        scsi_topology = prop_dict.get('config.storageDevice.scsiTopology')
        scsi_lun_ret = prop_dict.get('config.storageDevice.scsiLun')

    # Meaning there are no host bus adapters on the host
    if hbas_ret is None:
        return result
    host_hbas = hbas_ret.HostHostBusAdapter
    if not host_hbas:
        return result
    for hba in host_hbas:
        if hba.__class__.__name__ == 'HostInternetScsiHba':
            hba_key = hba.key
            break
    else:
        return result

    if scsi_topology is None:
        return result
    host_adapters = scsi_topology.adapter
    if not host_adapters:
        return result
    scsi_lun_key = None
    for adapter in host_adapters:
        if adapter.adapter == hba_key:
            if not getattr(adapter, 'target', None):
                return result
            for target in adapter.target:
                if (getattr(target.transport, 'address', None) and
                    target.transport.address[0] == target_portal and
                        target.transport.iScsiName == target_iqn):
                    if not target.lun:
                        return result
                    for lun in target.lun:
                        if 'host.ScsiDisk' in lun.scsiLun:
                            scsi_lun_key = lun.scsiLun
                            break
                    break
            break

    if scsi_lun_key is None:
        return result

    if scsi_lun_ret is None:
        return result
    host_scsi_luns = scsi_lun_ret.ScsiLun
    if not host_scsi_luns:
        return result
    for scsi_lun in host_scsi_luns:
        if scsi_lun.key == scsi_lun_key:
            return (scsi_lun.deviceName, scsi_lun.uuid)

    return result


def rescan_iscsi_hba(session, cluster=None, target_portal=None):
    """Rescan the iSCSI HBA to discover iSCSI targets."""
    host_mor = vm_util.get_host_ref(session, cluster)
    storage_system_mor = session._call_method(vim_util, "get_dynamic_property",
                                              host_mor, "HostSystem",
                                              "configManager.storageSystem")
    hbas_ret = session._call_method(vim_util,
                                    "get_dynamic_property",
                                    storage_system_mor,
                                    "HostStorageSystem",
                                    "storageDeviceInfo.hostBusAdapter")
    # Meaning there are no host bus adapters on the host
    if hbas_ret is None:
        return
    host_hbas = hbas_ret.HostHostBusAdapter
    if not host_hbas:
        return
    for hba in host_hbas:
        if hba.__class__.__name__ == 'HostInternetScsiHba':
            hba_device = hba.device
            if target_portal:
                # Check if iscsi host is already in the send target host list
                send_targets = getattr(hba, 'configuredSendTarget', [])
                send_tgt_portals = ['%s:%s' % (s.address, s.port) for s in
                                    send_targets]
                if target_portal not in send_tgt_portals:
                    _add_iscsi_send_target_host(session, storage_system_mor,
                                                hba_device, target_portal)
            break
    else:
        return
    LOG.debug(_("Rescanning HBA %s") % hba_device)
    session._call_method(session._get_vim(), "RescanHba", storage_system_mor,
                         hbaDevice=hba_device)
    LOG.debug(_("Rescanned HBA %s ") % hba_device)


def _add_iscsi_send_target_host(session, storage_system_mor, hba_device,
                                target_portal):
    """Adds the iscsi host to send target host list."""
    client_factory = session._get_vim().client.factory
    send_tgt = client_factory.create('ns0:HostInternetScsiHbaSendTarget')
    (send_tgt.address, send_tgt.port) = target_portal.split(':')
    LOG.debug(_("Adding iSCSI host %s to send targets"), send_tgt.address)
    session._call_method(
        session._get_vim(), "AddInternetScsiSendTargets", storage_system_mor,
        iScsiHbaDevice=hba_device, targets=[send_tgt])
