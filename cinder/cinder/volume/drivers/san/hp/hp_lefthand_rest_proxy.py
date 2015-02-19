#    (c) Copyright 2014 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
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
#
"""HP LeftHand SAN ISCSI REST Proxy."""

from cinder import context
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import units
from cinder import utils
from cinder.volume.driver import ISCSIDriver
from cinder.volume import volume_types
from oslo.config import cfg

LOG = logging.getLogger(__name__)

try:
    import hplefthandclient
    from hplefthandclient import client
    from hplefthandclient import exceptions as hpexceptions
except ImportError:
    LOG.error(_('Module hplefthandclient not installed.'))

hplefthand_opts = [
    cfg.StrOpt('hplefthand_api_url',
               default=None,
               help="HP LeftHand WSAPI Server Url like "
                    "https://<LeftHand ip>:8081/lhos"),
    cfg.StrOpt('hplefthand_username',
               default=None,
               help="HP LeftHand Super user username"),
    cfg.StrOpt('hplefthand_password',
               default=None,
               help="HP LeftHand Super user password",
               secret=True),
    cfg.StrOpt('hplefthand_clustername',
               default=None,
               help="HP LeftHand cluster name"),
    cfg.BoolOpt('hplefthand_iscsi_chap_enabled',
                default=False,
                help='Configure CHAP authentication for iSCSI connections '
                '(Default: Disabled)'),
    cfg.BoolOpt('hplefthand_debug',
                default=False,
                help="Enable HTTP debugging to LeftHand"),

]

CONF = cfg.CONF
CONF.register_opts(hplefthand_opts)


# map the extra spec key to the REST client option key
extra_specs_key_map = {
    'hplh:provisioning': 'isThinProvisioned',
    'hplh:ao': 'isAdaptiveOptimizationEnabled',
    'hplh:data_pl': 'dataProtectionLevel',
}

# map the extra spec value to the REST client option value
extra_specs_value_map = {
    'isThinProvisioned': {'thin': True, 'full': False},
    'isAdaptiveOptimizationEnabled': {'true': True, 'false': False},
    'dataProtectionLevel': {
        'r-0': 0, 'r-5': 1, 'r-10-2': 2, 'r-10-3': 3, 'r-10-4': 4, 'r-6': 5}
}


class HPLeftHandRESTProxy(ISCSIDriver):
    """Executes REST commands relating to HP/LeftHand SAN ISCSI volumes.

    Version history:
        1.0.0 - Initial REST iSCSI proxy
        1.0.1 - Added support for retype
        1.0.2 - Added support for volume migrate
        1.0.3 - Fixed bug #1285829, HP LeftHand backend assisted migration
                should check for snapshots
        1.0.4 - Fixed bug #1285925, LeftHand AO volume create performance
                improvement
    """

    VERSION = "1.0.4"

    device_stats = {}

    def __init__(self, *args, **kwargs):
        super(HPLeftHandRESTProxy, self).__init__(*args, **kwargs)
        self.configuration.append_config_values(hplefthand_opts)
        if not self.configuration.hplefthand_api_url:
            raise exception.NotFound(_("HPLeftHand url not found"))

        # blank is the only invalid character for cluster names
        # so we need to use it as a separator
        self.DRIVER_LOCATION = self.__class__.__name__ + ' %(cluster)s %(vip)s'

    def do_setup(self, context):
        """Set up LeftHand client."""
        try:
            self.client = client.HPLeftHandClient(
                self.configuration.hplefthand_api_url)
            self.client.login(
                self.configuration.hplefthand_username,
                self.configuration.hplefthand_password)

            if self.configuration.hplefthand_debug:
                self.client.debug_rest(True)

            cluster_info = self.client.getClusterByName(
                self.configuration.hplefthand_clustername)
            self.cluster_id = cluster_info['id']
            virtual_ips = cluster_info['virtualIPAddresses']
            self.cluster_vip = virtual_ips[0]['ipV4Address']
            self._update_backend_status()
        except hpexceptions.HTTPNotFound:
            raise exception.DriverNotInitialized(
                _('LeftHand cluster not found'))
        except Exception as ex:
            raise exception.DriverNotInitialized(ex)

    def check_for_setup_error(self):
        pass

    def get_version_string(self):
        return (_('REST %(proxy_ver)s hplefthandclient %(rest_ver)s') % {
            'proxy_ver': self.VERSION,
            'rest_ver': hplefthandclient.get_version_string()})

    def create_volume(self, volume):
        """Creates a volume."""
        try:
            # get the extra specs of interest from this volume's volume type
            volume_extra_specs = self._get_volume_extra_specs(volume)
            extra_specs = self._get_lh_extra_specs(
                volume_extra_specs,
                extra_specs_key_map.keys())

            # map the extra specs key/value pairs to key/value pairs
            # used as optional configuration values by the LeftHand backend
            optional = self._map_extra_specs(extra_specs)

            # if provisioning is not set, default to thin
            if 'isThinProvisioned' not in optional:
                optional['isThinProvisioned'] = True

            # AdaptiveOptimization defaults to 'true' if you don't specify the
            # value on a create, and that is the most efficient way to create
            # a volume. If you pass in 'false' or 'true' for AO, it will result
            # in an update operation following the create operation to set this
            # value, so it is best to not specify the value and let it default
            # to 'true'.
            if optional.get('isAdaptiveOptimizationEnabled'):
                del optional['isAdaptiveOptimizationEnabled']

            clusterName = self.configuration.hplefthand_clustername
            optional['clusterName'] = clusterName

            volume_info = self.client.createVolume(
                volume['name'], self.cluster_id,
                volume['size'] * units.GiB,
                optional)

            return self._update_provider(volume_info)
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def delete_volume(self, volume):
        """Deletes a volume."""
        try:
            volume_info = self.client.getVolumeByName(volume['name'])
            self.client.deleteVolume(volume_info['id'])
        except hpexceptions.HTTPNotFound:
            LOG.error(_("Volume did not exist. It will not be deleted"))
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def extend_volume(self, volume, new_size):
        """Extend the size of an existing volume."""
        try:
            volume_info = self.client.getVolumeByName(volume['name'])

            # convert GB to bytes
            options = {'size': int(new_size) * units.GiB}
            self.client.modifyVolume(volume_info['id'], options)
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def create_snapshot(self, snapshot):
        """Creates a snapshot."""
        try:
            volume_info = self.client.getVolumeByName(snapshot['volume_name'])

            option = {'inheritAccess': True}
            self.client.createSnapshot(snapshot['name'],
                                       volume_info['id'],
                                       option)
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def delete_snapshot(self, snapshot):
        """Deletes a snapshot."""
        try:
            snap_info = self.client.getSnapshotByName(snapshot['name'])
            self.client.deleteSnapshot(snap_info['id'])
        except hpexceptions.HTTPNotFound:
            LOG.error(_("Snapshot did not exist. It will not be deleted"))
        except hpexceptions.HTTPServerError as ex:
            in_use_msg = 'cannot be deleted because it is a clone point'
            if in_use_msg in ex.get_description():
                raise exception.SnapshotIsBusy(ex)

            raise exception.VolumeBackendAPIException(ex)

        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def get_volume_stats(self, refresh):
        """Gets volume stats."""
        if refresh:
            self._update_backend_status()

        return self.device_stats

    def _update_backend_status(self):
        data = {}
        backend_name = self.configuration.safe_get('volume_backend_name')
        data['volume_backend_name'] = backend_name or self.__class__.__name__
        data['reserved_percentage'] = 0
        data['storage_protocol'] = 'iSCSI'
        data['vendor_name'] = 'Hewlett-Packard'
        data['location_info'] = (self.DRIVER_LOCATION % {
            'cluster': self.configuration.hplefthand_clustername,
            'vip': self.cluster_vip})

        cluster_info = self.client.getCluster(self.cluster_id)

        total_capacity = cluster_info['spaceTotal']
        free_capacity = cluster_info['spaceAvailable']

        # convert to GB
        data['total_capacity_gb'] = int(total_capacity) / units.GiB
        data['free_capacity_gb'] = int(free_capacity) / units.GiB

        self.device_stats = data

    def initialize_connection(self, volume, connector):
        """Assigns the volume to a server.

        Assign any created volume to a compute node/host so that it can be
        used from that host. HP VSA requires a volume to be assigned
        to a server.
        """
        try:
            server_info = self._create_server(connector)
            volume_info = self.client.getVolumeByName(volume['name'])
            self.client.addServerAccess(volume_info['id'], server_info['id'])

            iscsi_properties = self._get_iscsi_properties(volume)

            if ('chapAuthenticationRequired' in server_info
                    and server_info['chapAuthenticationRequired']):
                iscsi_properties['auth_method'] = 'CHAP'
                iscsi_properties['auth_username'] = connector['initiator']
                iscsi_properties['auth_password'] = (
                    server_info['chapTargetSecret'])

            return {'driver_volume_type': 'iscsi', 'data': iscsi_properties}
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def terminate_connection(self, volume, connector, **kwargs):
        """Unassign the volume from the host."""
        try:
            volume_info = self.client.getVolumeByName(volume['name'])
            server_info = self.client.getServerByName(connector['host'])
            self.client.removeServerAccess(
                volume_info['id'],
                server_info['id'])
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def create_volume_from_snapshot(self, volume, snapshot):
        """Creates a volume from a snapshot."""
        try:
            snap_info = self.client.getSnapshotByName(snapshot['name'])
            volume_info = self.client.cloneSnapshot(
                volume['name'],
                snap_info['id'])
            return self._update_provider(volume_info)
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def create_cloned_volume(self, volume, src_vref):
        try:
            volume_info = self.client.getVolumeByName(src_vref['name'])
            self.client.cloneVolume(volume['name'], volume_info['id'])
        except Exception as ex:
            raise exception.VolumeBackendAPIException(ex)

    def _get_volume_extra_specs(self, volume):
        """Get extra specs from a volume."""
        extra_specs = {}
        type_id = volume.get('volume_type_id', None)
        if type_id is not None:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)
            extra_specs = volume_type.get('extra_specs')
        return extra_specs

    def _get_lh_extra_specs(self, extra_specs, valid_keys):
        """Get LeftHand extra_specs (valid_keys only)."""
        extra_specs_of_interest = {}
        for key, value in extra_specs.iteritems():
            if key in valid_keys:
                extra_specs_of_interest[key] = value
        return extra_specs_of_interest

    def _map_extra_specs(self, extra_specs):
        """Map the extra spec key/values to LeftHand key/values."""
        client_options = {}
        for key, value in extra_specs.iteritems():
            # map extra spec key to lh client option key
            client_key = extra_specs_key_map[key]
            # map extra spect value to lh client option value
            try:
                value_map = extra_specs_value_map[client_key]
                # an invalid value will throw KeyError
                client_value = value_map[value]
                client_options[client_key] = client_value
            except KeyError:
                LOG.error(_("'%(value)s' is an invalid value "
                            "for extra spec '%(key)s'") %
                          {'value': value, 'key': key})
        return client_options

    def _update_provider(self, volume_info):
        # TODO(justinsb): Is this always 1? Does it matter?
        cluster_interface = '1'
        iscsi_portal = self.cluster_vip + ":3260," + cluster_interface

        return {'provider_location': (
            "%s %s %s" % (iscsi_portal, volume_info['iscsiIqn'], 0))}

    def _create_server(self, connector):
        server_info = None
        chap_enabled = self.configuration.hplefthand_iscsi_chap_enabled
        try:
            server_info = self.client.getServerByName(connector['host'])
            chap_secret = server_info['chapTargetSecret']
            if not chap_enabled and chap_secret:
                LOG.warning(_('CHAP secret exists for host %s but CHAP is '
                              'disabled') % connector['host'])
            if chap_enabled and chap_secret is None:
                LOG.warning(_('CHAP is enabled, but server secret not '
                              'configured on server %s') % connector['host'])
            return server_info
        except hpexceptions.HTTPNotFound:
            # server does not exist, so create one
            pass

        optional = None
        if chap_enabled:
            chap_secret = utils.generate_password()
            optional = {'chapName': connector['initiator'],
                        'chapTargetSecret': chap_secret,
                        'chapAuthenticationRequired': True
                        }
        server_info = self.client.createServer(connector['host'],
                                               connector['initiator'],
                                               optional)
        return server_info

    def create_export(self, context, volume):
        pass

    def ensure_export(self, context, volume):
        pass

    def remove_export(self, context, volume):
        pass

    def retype(self, ctxt, volume, new_type, diff, host):
        """Convert the volume to be of the new type.

        Returns a boolean indicating whether the retype occurred.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to retype
        :param new_type: A dictionary describing the volume type to convert to
        :param diff: A dictionary with the difference between the two types
        :param host: A dictionary describing the host, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug(_('enter: retype: id=%(id)s, new_type=%(new_type)s,'
                    'diff=%(diff)s, host=%(host)s') % {'id': volume['id'],
                                                       'new_type': new_type,
                                                       'diff': diff,
                                                       'host': host})
        try:
            volume_info = self.client.getVolumeByName(volume['name'])
        except hpexceptions.HTTPNotFound:
            raise exception.VolumeNotFound(volume_id=volume['id'])

        try:
            # pick out the LH extra specs
            new_extra_specs = dict(new_type).get('extra_specs')
            lh_extra_specs = self._get_lh_extra_specs(
                new_extra_specs,
                extra_specs_key_map.keys())

            LOG.debug(_('LH specs=%(specs)s') % {'specs': lh_extra_specs})

            # only set the ones that have changed
            changed_extra_specs = {}
            for key, value in lh_extra_specs.iteritems():
                (old, new) = diff['extra_specs'][key]
                if old != new:
                    changed_extra_specs[key] = value

            # map extra specs to LeftHand options
            options = self._map_extra_specs(changed_extra_specs)
            if len(options) > 0:
                self.client.modifyVolume(volume_info['id'], options)
            return True

        except Exception as ex:
            LOG.warning("%s" % ex)

        return False

    def migrate_volume(self, ctxt, volume, host):
        """Migrate the volume to the specified host.

        Backend assisted volume migration will occur if and only if;

        1. Same LeftHand backend
        2. Volume cannot be attached
        3. Volumes with snapshots cannot be migrated
        4. Source and Destination clusters must be in the same management group

        Volume re-type is not supported.

        Returns a boolean indicating whether the migration occurred, as well as
        model_update.

        :param ctxt: Context
        :param volume: A dictionary describing the volume to migrate
        :param host: A dictionary describing the host to migrate to, where
                     host['host'] is its name, and host['capabilities'] is a
                     dictionary of its reported capabilities.
        """
        LOG.debug(_('enter: migrate_volume: id=%(id)s, host=%(host)s, '
                    'cluster=%(cluster)s') % {
                        'id': volume['id'],
                        'host': host,
                        'cluster': self.configuration.hplefthand_clustername})

        false_ret = (False, None)
        if 'location_info' not in host['capabilities']:
            return false_ret

        host_location = host['capabilities']['location_info']
        (driver, cluster, vip) = host_location.split(' ')
        try:
            # get the cluster info, if it exists and compare
            cluster_info = self.client.getClusterByName(cluster)
            LOG.debug(_('Clister info: %s') % cluster_info)
            virtual_ips = cluster_info['virtualIPAddresses']

            if driver != self.__class__.__name__:
                LOG.info(_("Cannot provide backend assisted migration for "
                           "volume: %s because volume is from a different "
                           "backend.") % volume['name'])
                return false_ret
            if vip != virtual_ips[0]['ipV4Address']:
                LOG.info(_("Cannot provide backend assisted migration for "
                           "volume: %s because cluster exists in different "
                           "management group.") % volume['name'])
                return false_ret

        except hpexceptions.HTTPNotFound:
            LOG.info(_("Cannot provide backend assisted migration for "
                       "volume: %s because cluster exists in different "
                       "management group.") % volume['name'])
            return false_ret

        try:
            volume_info = self.client.getVolumeByName(volume['name'])
            LOG.debug(_('Volume info: %s') % volume_info)

            # can't migrate if server is attached
            if volume_info['iscsiSessions'] is not None:
                LOG.info(_("Cannot provide backend assisted migration "
                           "for volume: %s because the volume has been "
                           "exported.") % volume['name'])
                return false_ret

            # can't migrate if volume has snapshots
            snap_info = self.client.getVolume(
                volume_info['id'],
                'fields=snapshots,snapshots[resource[members[name]]]')
            LOG.debug(_('Snapshot info: %s') % snap_info)
            if snap_info['snapshots']['resource'] is not None:
                LOG.info(_("Cannot provide backend assisted migration "
                           "for volume: %s because the volume has "
                           "snapshots.") % volume['name'])
                return false_ret

            options = {'clusterName': cluster}
            self.client.modifyVolume(volume_info['id'], options)
        except hpexceptions.HTTPNotFound:
            LOG.info(_("Cannot provide backend assisted migration for "
                       "volume: %s because volume does not exist in this "
                       "management group.") % volume['name'])
            return false_ret
        except hpexceptions.HTTPServerError as ex:
            LOG.error(ex)
            return false_ret

        return (True, None)
