# Copyright 2012 Pedro Navarro Perez
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
Volume driver for Windows Server 2012

This driver requires ISCSI target role installed

"""

import os

from oslo.config import cfg

from cinder.image import image_utils
from cinder.openstack.common import log as logging
from cinder.volume import driver
from cinder.volume.drivers.windows import windows_utils

LOG = logging.getLogger(__name__)

windows_opts = [
    cfg.StrOpt('windows_iscsi_lun_path',
               default='C:\iSCSIVirtualDisks',
               help='Path to store VHD backed volumes'),
]

CONF = cfg.CONF
CONF.register_opts(windows_opts)


class WindowsDriver(driver.ISCSIDriver):
    """Executes volume driver commands on Windows Storage server."""

    VERSION = '1.0.0'

    def __init__(self, *args, **kwargs):
        super(WindowsDriver, self).__init__(*args, **kwargs)
        self.configuration = kwargs.get('configuration', None)
        if self.configuration:
            self.configuration.append_config_values(windows_opts)

    def do_setup(self, context):
        """Setup the Windows Volume driver.

        Called one time by the manager after the driver is loaded.
        Validate the flags we care about
        """
        self.utils = windows_utils.WindowsUtils()

    def check_for_setup_error(self):
        """Check that the driver is working and can communicate."""
        self.utils.check_for_setup_error()

    def initialize_connection(self, volume, connector):
        """Driver entry point to attach a volume to an instance."""
        initiator_name = connector['initiator']
        target_name = volume['provider_location']

        self.utils.associate_initiator_with_iscsi_target(initiator_name,
                                                         target_name)

        properties = self.utils.get_host_information(volume, target_name)

        return {
            'driver_volume_type': 'iscsi',
            'data': properties,
        }

    def terminate_connection(self, volume, connector, **kwargs):
        """Driver entry point to unattach a volume from an instance.

        Unmask the LUN on the storage system so the given initiator can no
        longer access it.
        """
        initiator_name = connector['initiator']
        target_name = volume['provider_location']
        self.utils.delete_iscsi_target(initiator_name, target_name)

    def create_volume(self, volume):
        """Driver entry point for creating a new volume."""
        vhd_path = self.local_path(volume)
        vol_name = volume['name']
        vol_size = volume['size']

        self.utils.create_volume(vhd_path, vol_name, vol_size)

    def local_path(self, volume):
        base_vhd_folder = self.configuration.windows_iscsi_lun_path
        if not os.path.exists(base_vhd_folder):
            LOG.debug(_('Creating folder %s '), base_vhd_folder)
            os.makedirs(base_vhd_folder)
        return os.path.join(base_vhd_folder, str(volume['name']) + ".vhd")

    def delete_volume(self, volume):
        """Driver entry point for destroying existing volumes."""
        vol_name = volume['name']
        vhd_path = self.local_path(volume)

        self.utils.delete_volume(vol_name, vhd_path)

    def create_snapshot(self, snapshot):
        """Driver entry point for creating a snapshot."""
        # Getting WT_Snapshot class
        vol_name = snapshot['volume_name']
        snapshot_name = snapshot['name']

        self.utils.create_snapshot(vol_name, snapshot_name)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Driver entry point for exporting snapshots as volumes."""
        snapshot_name = snapshot['name']
        vol_name = volume['name']
        self.utils.create_volume_from_snapshot(vol_name, snapshot_name)

    def delete_snapshot(self, snapshot):
        """Driver entry point for deleting a snapshot."""
        snapshot_name = snapshot['name']
        self.utils.delete_snapshot(snapshot_name)

    def _do_export(self, _ctx, volume, ensure=False):
        """Do all steps to get disk exported as LUN 0 at separate target.

        :param volume: reference of volume to be exported
        :param ensure: if True, ignore errors caused by already existing
            resources
        :return: iscsiadm-formatted provider location string
        """
        target_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                                volume['name'])
        self.utils.create_iscsi_target(target_name, ensure)

        # Get the disk to add
        vol_name = volume['name']
        self.utils.add_disk_to_target(vol_name, target_name)

        return target_name

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        self._do_export(context, volume, ensure=True)

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        loc = self._do_export(context, volume, ensure=False)
        return {'provider_location': loc}

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume.
        """
        target_name = "%s%s" % (self.configuration.iscsi_target_prefix,
                                volume['name'])

        self.utils.remove_iscsi_target(target_name)

    def copy_image_to_volume(self, context, volume, image_service, image_id):
        """Fetch the image from image_service and write it to the volume."""
        # Convert to VHD and file back to VHD
        image_utils.fetch_to_vhd(context, image_service, image_id,
                                 self.local_path(volume),
                                 self.configuration.volume_dd_blocksize)

    def copy_volume_to_image(self, context, volume, image_service, image_meta):
        """Copy the volume to the specified image."""

        # Copy the volume to the image conversion dir
        temp_vhd_path = os.path.join(self.configuration.image_conversion_dir,
                                     str(image_meta['id']) + ".vhd")
        self.utils.copy_vhd_disk(self.local_path(volume), temp_vhd_path)
        image_utils.upload_volume(context, image_service, image_meta,
                                  temp_vhd_path, 'vpc')

    def create_cloned_volume(self, volume, src_vref):
        """Creates a clone of the specified volume."""
        # Create a new volume
        # Copy VHD file of the volume to clone to the created volume
        self.create_volume(volume)
        self.utils.copy_vhd_disk(self.local_path(src_vref),
                                 self.local_path(volume))

    def get_volume_stats(self, refresh=False):
        """Get volume stats.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self._update_volume_stats()

        return self._stats

    def _update_volume_stats(self):
        """Retrieve stats info for Windows device."""

        LOG.debug(_("Updating volume stats"))
        data = {}
        backend_name = self.__class__.__name__
        if self.configuration:
            backend_name = self.configuration.safe_get('volume_backend_name')
        data["volume_backend_name"] = backend_name or self.__class__.__name__
        data["vendor_name"] = 'Microsoft'
        data["driver_version"] = self.VERSION
        data["storage_protocol"] = 'iSCSI'
        data['total_capacity_gb'] = 'infinite'
        data['free_capacity_gb'] = 'infinite'
        data['reserved_percentage'] = 100
        data['QoS_support'] = False
        self._stats = data

    def extend_volume(self, volume, new_size):
        """Extend an Existing Volume."""
        old_size = volume['size']
        LOG.debug(_("Extend volume from %(old_size)s GB to %(new_size)s GB."),
                  {'old_size': old_size, 'new_size': new_size})
        additional_size = (new_size - old_size) * 1024
        self.utils.extend(volume['name'], additional_size)
