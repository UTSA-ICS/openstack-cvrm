# Copyright (c) 2012 - 2014 EMC Corporation, Inc.
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
iSCSI Drivers for EMC VNX array based on CLI.

"""

from cinder import exception
from cinder.openstack.common import log as logging
from cinder import utils
from cinder.volume import driver
from cinder.volume.drivers.emc import emc_vnx_cli

LOG = logging.getLogger(__name__)


class EMCCLIISCSIDriver(driver.ISCSIDriver):
    """EMC ISCSI Drivers for VNX using CLI."""

    def __init__(self, *args, **kwargs):

        super(EMCCLIISCSIDriver, self).__init__(*args, **kwargs)
        self.cli = emc_vnx_cli.EMCVnxCli(
            'iSCSI',
            configuration=self.configuration)

    def check_for_setup_error(self):
        pass

    def create_volume(self, volume):
        """Creates a EMC(VMAX/VNX) volume."""
        self.cli.create_volume(volume)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        self.cli.create_volume_from_snapshot(volume, snapshot)

    def create_cloned_volume(self, volume, src_vref):
        """Creates a cloned volume."""
        self.cli.create_cloned_volume(volume, src_vref)

    def delete_volume(self, volume):
        """Deletes an EMC volume."""
        self.cli.delete_volume(volume)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        self.cli.create_snapshot(snapshot)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        self.cli.delete_snapshot(snapshot)

    def ensure_export(self, context, volume):
        """Driver entry point to get the export info for an existing volume."""
        pass

    def create_export(self, context, volume):
        """Driver entry point to get the export info for a new volume."""
        self.cli.create_export(context, volume)

    def remove_export(self, context, volume):
        """Driver entry point to remove an export for a volume."""
        pass

    def check_for_export(self, context, volume_id):
        """Make sure volume is exported."""
        pass

    def extend_volume(self, volume, new_size):
        self.cli.extend_volume(volume, new_size)

    def initialize_connection(self, volume, connector):
        """Initializes the connection and returns connection info.

        The iscsi driver returns a driver_volume_type of 'iscsi'.
        the format of the driver data is defined in vnx_get_iscsi_properties.

        :param volume: volume to be attached.
        :param connector: connector information.
        :returns: dictionary containing iscsi_properties.
        Example return value:
            {
                'driver_volume_type': 'iscsi'
                'data': {
                    'target_discovered': True,
                    'target_iqn': 'iqn.2010-10.org.openstack:volume-00000001',
                    'target_portal': '127.0.0.0.1:3260',
                    'volume_id': '12345678-1234-4321-1234-123456789012',
                }
            }
        """
        @utils.synchronized('emc-connection-' + connector['host'],
                            external=True)
        def do_initialize_connection():
            self.cli.initialize_connection(volume, connector)
        do_initialize_connection()

        iscsi_properties = self.vnx_get_iscsi_properties(volume, connector)
        return {
            'driver_volume_type': 'iscsi',
            'data': {
                'target_discovered': True,
                'target_iqn': iscsi_properties['target_iqn'],
                'target_lun': iscsi_properties['target_lun'],
                'target_portal': iscsi_properties['target_portal'],
                'volume_id': iscsi_properties['volume_id']
            }
        }

    def _do_iscsi_discovery(self, volume):

        LOG.warn(_("iSCSI provider_location not stored for volume %s, "
                 "using discovery.") % (volume['name']))

        (out, _err) = self._execute('iscsiadm', '-m', 'discovery',
                                    '-t', 'sendtargets', '-p',
                                    self.configuration.iscsi_ip_address,
                                    run_as_root=True)
        targets = []
        for target in out.splitlines():
            targets.append(target)

        return targets

    def vnx_get_iscsi_properties(self, volume, connector):
        """Gets iscsi configuration.

        We ideally get saved information in the volume entity, but fall back
        to discovery if need be. Discovery may be completely removed in future
        The properties are:

        :target_discovered:    boolean indicating whether discovery was used

        :target_iqn:    the IQN of the iSCSI target

        :target_portal:    the portal of the iSCSI target

        :target_lun:    the lun of the iSCSI target

        :volume_id:    the UUID of the volume

        :auth_method:, :auth_username:, :auth_password:

            the authentication details. Right now, either auth_method is not
            present meaning no authentication, or auth_method == `CHAP`
            meaning use CHAP with the specified credentials.
        """
        properties = {}

        location = self._do_iscsi_discovery(volume)
        if not location:
            raise exception.InvalidVolume(_("Could not find iSCSI export "
                                          " for volume %s") %
                                          (volume['name']))

        LOG.debug(_("ISCSI Discovery: Found %s") % (location))
        properties['target_discovered'] = True

        hostname = connector['host']
        storage_group = hostname
        device_info = self.cli.find_device_details(volume, storage_group)
        if device_info is None or device_info['hostlunid'] is None:
            exception_message = (_("Cannot find device number for volume %s")
                                 % volume['name'])
            raise exception.VolumeBackendAPIException(data=exception_message)

        device_number = device_info['hostlunid']
        device_sp = device_info['ownersp']
        endpoints = []

        if device_sp:
            # endpoints example:
            # [iqn.1992-04.com.emc:cx.apm00123907237.a8,
            # iqn.1992-04.com.emc:cx.apm00123907237.a9]
            endpoints = self.cli._find_iscsi_protocol_endpoints(device_sp)

        foundEndpoint = False
        for loc in location:
            results = loc.split(" ")
            properties['target_portal'] = results[0].split(",")[0]
            properties['target_iqn'] = results[1]
            # for VNX, find the target_iqn that matches the endpoint
            # target_iqn example: iqn.1992-04.com.emc:cx.apm00123907237.a8
            # or iqn.1992-04.com.emc:cx.apm00123907237.b8
            if not device_sp:
                break
            for endpoint in endpoints:
                if properties['target_iqn'] == endpoint:
                    LOG.debug(_("Found iSCSI endpoint: %s") % endpoint)
                    foundEndpoint = True
                    break
            if foundEndpoint:
                break

        if device_sp and not foundEndpoint:
            LOG.warn(_("ISCSI endpoint not found for SP %(sp)s ")
                     % {'sp': device_sp})

        properties['target_lun'] = device_number

        properties['volume_id'] = volume['id']

        auth = volume['provider_auth']
        if auth:
            (auth_method, auth_username, auth_secret) = auth.split()

            properties['auth_method'] = auth_method
            properties['auth_username'] = auth_username
            properties['auth_password'] = auth_secret

        return properties

    def terminate_connection(self, volume, connector, **kwargs):
        """Disallow connection from connector."""
        @utils.synchronized('emc-connection-' + connector['host'],
                            external=True)
        def do_terminate_connection():
            self.cli.terminate_connection(volume, connector)
        do_terminate_connection()

    def get_volume_stats(self, refresh=False):
        """Get volume status.

        If 'refresh' is True, run update the stats first.
        """
        if refresh:
            self.update_volume_stats()
            LOG.info(_("update_volume_status:%s"), self._stats)

        return self._stats

    def update_volume_stats(self):
        """Retrieve status info from volume group."""
        LOG.debug(_("Updating volume status"))
        # retrieving the volume update from the VNX
        data = self.cli.update_volume_status()
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or 'EMCCLIISCSIDriver'
        data['storage_protocol'] = 'iSCSI'
        self._stats = data
