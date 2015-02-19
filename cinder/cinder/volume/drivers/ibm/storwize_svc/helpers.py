# Copyright 2014 IBM Corp.
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
#

import random
import re
import six
import unicodedata

from eventlet import greenthread

from cinder import context
from cinder import exception
from cinder.openstack.common import excutils
from cinder.openstack.common import log as logging
from cinder.openstack.common import loopingcall
from cinder.openstack.common import strutils
from cinder import utils
from cinder.volume.drivers.ibm.storwize_svc import ssh as storwize_ssh
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


class StorwizeHelpers(object):
    def __init__(self, run_ssh):
        self.ssh = storwize_ssh.StorwizeSSH(run_ssh)
        self.check_fcmapping_interval = 3

    @staticmethod
    def handle_keyerror(cmd, out):
        msg = (_('Could not find key in output of command %(cmd)s: %(out)s')
               % {'out': out, 'cmd': cmd})
        raise exception.VolumeBackendAPIException(data=msg)

    def compression_enabled(self):
        """Return whether or not compression is enabled for this system."""
        resp = self.ssh.lslicense()
        keys = ['license_compression_enclosures',
                'license_compression_capacity']
        for key in keys:
            if resp.get(key, '0') != '0':
                return True
        return False

    def get_system_info(self):
        """Return system's name, ID, and code level."""
        resp = self.ssh.lssystem()
        level = resp['code_level']
        match_obj = re.search('([0-9].){3}[0-9]', level)
        if match_obj is None:
            msg = _('Failed to get code level (%s).') % level
            raise exception.VolumeBackendAPIException(data=msg)
        code_level = match_obj.group().split('.')
        return {'code_level': tuple([int(x) for x in code_level]),
                'system_name': resp['name'],
                'system_id': resp['id']}

    def get_pool_attrs(self, pool):
        """Return attributes for the specified pool."""
        return self.ssh.lsmdiskgrp(pool)

    def get_available_io_groups(self):
        """Return list of available IO groups."""
        iogrps = []
        resp = self.ssh.lsiogrp()
        for iogrp in resp:
            try:
                if int(iogrp['node_count']) > 0:
                    iogrps.append(int(iogrp['id']))
            except KeyError:
                self.handle_keyerror('lsiogrp', iogrp)
            except ValueError:
                msg = (_('Expected integer for node_count, '
                         'svcinfo lsiogrp returned: %(node)s') %
                       {'node': iogrp['node_count']})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
        return iogrps

    def get_node_info(self):
        """Return dictionary containing information on system's nodes."""
        nodes = {}
        resp = self.ssh.lsnode()
        for node_data in resp:
            try:
                if node_data['status'] != 'online':
                    continue
                node = {}
                node['id'] = node_data['id']
                node['name'] = node_data['name']
                node['IO_group'] = node_data['IO_group_id']
                node['iscsi_name'] = node_data['iscsi_name']
                node['WWNN'] = node_data['WWNN']
                node['status'] = node_data['status']
                node['WWPN'] = []
                node['ipv4'] = []
                node['ipv6'] = []
                node['enabled_protocols'] = []
                nodes[node['id']] = node
            except KeyError:
                self.handle_keyerror('lsnode', node_data)
        return nodes

    def add_iscsi_ip_addrs(self, storage_nodes):
        """Add iSCSI IP addresses to system node information."""
        resp = self.ssh.lsportip()
        for ip_data in resp:
            try:
                state = ip_data['state']
                if ip_data['node_id'] in storage_nodes and (
                        state == 'configured' or state == 'online'):
                    node = storage_nodes[ip_data['node_id']]
                    if len(ip_data['IP_address']):
                        node['ipv4'].append(ip_data['IP_address'])
                    if len(ip_data['IP_address_6']):
                        node['ipv6'].append(ip_data['IP_address_6'])
            except KeyError:
                self.handle_keyerror('lsportip', ip_data)

    def add_fc_wwpns(self, storage_nodes):
        """Add FC WWPNs to system node information."""
        for key in storage_nodes:
            node = storage_nodes[key]
            resp = self.ssh.lsnode(node_id=node['id'])
            wwpns = set(node['WWPN'])
            for i, s in resp.select('port_id', 'port_status'):
                if 'unconfigured' != s:
                    wwpns.add(i)
            node['WWPN'] = list(wwpns)
            LOG.info(_('WWPN on node %(node)s: %(wwpn)s')
                     % {'node': node['id'], 'wwpn': node['WWPN']})

    def add_chap_secret_to_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        chap_secret = utils.generate_password()
        self.ssh.add_chap_secret(chap_secret, host_name)
        return chap_secret

    def get_chap_secret_for_host(self, host_name):
        """Generate and store a randomly-generated CHAP secret for the host."""
        resp = self.ssh.lsiscsiauth()
        host_found = False
        for host_data in resp:
            try:
                if host_data['name'] == host_name:
                    host_found = True
                    if host_data['iscsi_auth_method'] == 'chap':
                        return host_data['iscsi_chap_secret']
            except KeyError:
                self.handle_keyerror('lsiscsiauth', host_data)
        if not host_found:
            msg = _('Failed to find host %s') % host_name
            raise exception.VolumeBackendAPIException(data=msg)
        return None

    def get_conn_fc_wwpns(self, host):
        wwpns = set()
        resp = self.ssh.lsfabric(host=host)
        for wwpn in resp.select('local_wwpn'):
            if wwpn is not None:
                wwpns.add(wwpn)
        return list(wwpns)

    def get_host_from_connector(self, connector):
        """Return the Storwize host described by the connector."""
        LOG.debug(_('enter: get_host_from_connector: %s') % connector)

        # If we have FC information, we have a faster lookup option
        host_name = None
        if 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                resp = self.ssh.lsfabric(wwpn=wwpn)
                for wwpn_info in resp:
                    try:
                        if (wwpn_info['remote_wwpn'] and
                                wwpn_info['name'] and
                                wwpn_info['remote_wwpn'].lower() ==
                                wwpn.lower()):
                            host_name = wwpn_info['name']
                    except KeyError:
                        self.handle_keyerror('lsfabric', wwpn_info)

        # That didn't work, so try exhaustive search
        if host_name is None:
            hosts_info = self.ssh.lshost()
            for name in hosts_info.select('name'):
                resp = self.ssh.lshost(host=name)
                for iscsi, wwpn in resp.select('iscsi_name', 'WWPN'):
                    if ('initiator' in connector and
                            iscsi == connector['initiator']):
                        host_name = name
                    elif ('wwpns' in connector and
                          len(connector['wwpns']) and
                          wwpn and
                          wwpn.lower() in
                          [str(x).lower() for x in connector['wwpns']]):
                        host_name = name

        LOG.debug(_('leave: get_host_from_connector: host %s') % host_name)
        return host_name

    def create_host(self, connector):
        """Create a new host on the storage system.

        We create a host name and associate it with the given connection
        information.  The host name will be a cleaned up version of the given
        host name (at most 55 characters), plus a random 8-character suffix to
        avoid collisions. The total length should be at most 63 characters.
        """
        LOG.debug(_('enter: create_host: host %s') % connector['host'])

        # Before we start, make sure host name is a string and that we have at
        # least one port.
        host_name = connector['host']
        if not isinstance(host_name, six.string_types):
            msg = _('create_host: Host name is not unicode or string')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        ports = []
        if 'initiator' in connector:
            ports.append(['initiator', '%s' % connector['initiator']])
        if 'wwpns' in connector:
            for wwpn in connector['wwpns']:
                ports.append(['wwpn', '%s' % wwpn])
        if not len(ports):
            msg = _('create_host: No initiators or wwpns supplied.')
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        # Build a host name for the Storwize host - first clean up the name
        if isinstance(host_name, unicode):
            host_name = unicodedata.normalize('NFKD', host_name).encode(
                'ascii', 'replace').decode('ascii')

        for num in range(0, 128):
            ch = str(chr(num))
            if not ch.isalnum() and ch not in [' ', '.', '-', '_']:
                host_name = host_name.replace(ch, '-')

        # Storwize doesn't like hostname that doesn't starts with letter or _.
        if not re.match('^[A-Za-z]', host_name):
            host_name = '_' + host_name

        # Add a random 8-character suffix to avoid collisions
        rand_id = str(random.randint(0, 99999999)).zfill(8)
        host_name = '%s-%s' % (host_name[:55], rand_id)

        # Create a host with one port
        port = ports.pop(0)
        self.ssh.mkhost(host_name, port[0], port[1])

        # Add any additional ports to the host
        for port in ports:
            self.ssh.addhostport(host_name, port[0], port[1])

        LOG.debug(_('leave: create_host: host %(host)s - %(host_name)s') %
                  {'host': connector['host'], 'host_name': host_name})
        return host_name

    def delete_host(self, host_name):
        self.ssh.rmhost(host_name)

    def map_vol_to_host(self, volume_name, host_name, multihostmap):
        """Create a mapping between a volume to a host."""

        LOG.debug(_('enter: map_vol_to_host: volume %(volume_name)s to '
                    'host %(host_name)s')
                  % {'volume_name': volume_name, 'host_name': host_name})

        # Check if this volume is already mapped to this host
        mapped = False
        luns_used = []
        result_lun = '-1'
        resp = self.ssh.lshostvdiskmap(host_name)
        for mapping_info in resp:
            luns_used.append(int(mapping_info['SCSI_id']))
            if mapping_info['vdisk_name'] == volume_name:
                mapped = True
                result_lun = mapping_info['SCSI_id']

        if not mapped:
            # Find unused lun
            luns_used.sort()
            result_lun = str(len(luns_used))
            for index, n in enumerate(luns_used):
                if n > index:
                    result_lun = str(index)
                    break
            self.ssh.mkvdiskhostmap(host_name, volume_name, result_lun,
                                    multihostmap)

        LOG.debug(_('leave: map_vol_to_host: LUN %(result_lun)s, volume '
                    '%(volume_name)s, host %(host_name)s') %
                  {'result_lun': result_lun,
                   'volume_name': volume_name,
                   'host_name': host_name})
        return int(result_lun)

    def unmap_vol_from_host(self, volume_name, host_name):
        """Unmap the volume and delete the host if it has no more mappings."""

        LOG.debug(_('enter: unmap_vol_from_host: volume %(volume_name)s from '
                    'host %(host_name)s')
                  % {'volume_name': volume_name, 'host_name': host_name})

        # Check if the mapping exists
        resp = self.ssh.lsvdiskhostmap(volume_name)
        if not len(resp):
            LOG.warning(_('unmap_vol_from_host: No mapping of volume '
                          '%(vol_name)s to any host found.') %
                        {'vol_name': volume_name})
            return
        if host_name is None:
            if len(resp) > 1:
                LOG.warning(_('unmap_vol_from_host: Multiple mappings of '
                              'volume %(vol_name)s found, no host '
                              'specified.') % {'vol_name': volume_name})
                return
            else:
                host_name = resp[0]['host_name']
        else:
            found = False
            for h in resp.select('host_name'):
                if h == host_name:
                    found = True
            if not found:
                LOG.warning(_('unmap_vol_from_host: No mapping of volume '
                              '%(vol_name)s to host %(host)s found.') %
                            {'vol_name': volume_name, 'host': host_name})

        # We now know that the mapping exists
        self.ssh.rmvdiskhostmap(host_name, volume_name)

        # If this host has no more mappings, delete it
        resp = self.ssh.lshostvdiskmap(host_name)
        if not len(resp):
            self.delete_host(host_name)

        LOG.debug(_('leave: unmap_vol_from_host: volume %(volume_name)s from '
                    'host %(host_name)s')
                  % {'volume_name': volume_name, 'host_name': host_name})

    @staticmethod
    def build_default_opts(config):
        # Ignore capitalization
        protocol = config.storwize_svc_connection_protocol
        if protocol.lower() == 'fc':
            protocol = 'FC'
        elif protocol.lower() == 'iscsi':
            protocol = 'iSCSI'

        opt = {'rsize': config.storwize_svc_vol_rsize,
               'warning': config.storwize_svc_vol_warning,
               'autoexpand': config.storwize_svc_vol_autoexpand,
               'grainsize': config.storwize_svc_vol_grainsize,
               'compression': config.storwize_svc_vol_compression,
               'easytier': config.storwize_svc_vol_easytier,
               'protocol': protocol,
               'multipath': config.storwize_svc_multipath_enabled,
               'iogrp': config.storwize_svc_vol_iogrp}
        return opt

    @staticmethod
    def check_vdisk_opts(state, opts):
        # Check that rsize is either -1 or between 0 and 100
        if not (opts['rsize'] >= -1 and opts['rsize'] <= 100):
            raise exception.InvalidInput(
                reason=_('Illegal value specified for storwize_svc_vol_rsize: '
                         'set to either a percentage (0-100) or -1'))

        # Check that warning is either -1 or between 0 and 100
        if not (opts['warning'] >= -1 and opts['warning'] <= 100):
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_warning: '
                         'set to a percentage (0-100)'))

        # Check that grainsize is 32/64/128/256
        if opts['grainsize'] not in [32, 64, 128, 256]:
            raise exception.InvalidInput(
                reason=_('Illegal value specified for '
                         'storwize_svc_vol_grainsize: set to either '
                         '32, 64, 128, or 256'))

        # Check that compression is supported
        if opts['compression'] and not state['compression_enabled']:
            raise exception.InvalidInput(
                reason=_('System does not support compression'))

        # Check that rsize is set if compression is set
        if opts['compression'] and opts['rsize'] == -1:
            raise exception.InvalidInput(
                reason=_('If compression is set to True, rsize must '
                         'also be set (not equal to -1)'))

        # Check that the requested protocol is enabled
        if opts['protocol'] not in state['enabled_protocols']:
            raise exception.InvalidInput(
                reason=_('Illegal value %(prot)s specified for '
                         'storwize_svc_connection_protocol: '
                         'valid values are %(enabled)s')
                % {'prot': opts['protocol'],
                   'enabled': ','.join(state['enabled_protocols'])})

        if opts['iogrp'] not in state['available_iogrps']:
            avail_grps = ''.join(str(e) for e in state['available_iogrps'])
            raise exception.InvalidInput(
                reason=_('I/O group %(iogrp)d is not valid; available '
                         'I/O groups are %(avail)s')
                % {'iogrp': opts['iogrp'],
                   'avail': avail_grps})

    def get_vdisk_params(self, config, state, type_id, volume_type=None):
        """Return the parameters for creating the vdisk.

        Takes volume type and defaults from config options into account.
        """
        opts = self.build_default_opts(config)
        if volume_type is None and type_id is not None:
            ctxt = context.get_admin_context()
            volume_type = volume_types.get_volume_type(ctxt, type_id)
        if volume_type:
            specs = dict(volume_type).get('extra_specs')
            for k, value in specs.iteritems():
                # Get the scope, if using scope format
                key_split = k.split(':')
                if len(key_split) == 1:
                    scope = None
                    key = key_split[0]
                else:
                    scope = key_split[0]
                    key = key_split[1]

                # We generally do not look at capabilities in the driver, but
                # protocol is a special case where the user asks for a given
                # protocol and we want both the scheduler and the driver to act
                # on the value.
                if ((not scope or scope == 'capabilities') and
                        key == 'storage_protocol'):
                    scope = None
                    key = 'protocol'
                    words = value.split()
                    if not (words and len(words) == 2 and words[0] == '<in>'):
                        LOG.error(_('Protocol must be specified as '
                                    '\'<in> iSCSI\' or \'<in> FC\'.'))
                    del words[0]
                    value = words[0]

                # Any keys that the driver should look at should have the
                # 'drivers' scope.
                if scope and scope != 'drivers':
                    continue

                if key in opts:
                    this_type = type(opts[key]).__name__
                    if this_type == 'int':
                        value = int(value)
                    elif this_type == 'bool':
                        value = strutils.bool_from_string(value)
                    opts[key] = value

        self.check_vdisk_opts(state, opts)
        return opts

    @staticmethod
    def _get_vdisk_create_params(opts):
        easytier = 'on' if opts['easytier'] else 'off'

        if opts['rsize'] == -1:
            params = []
        else:
            params = ['-rsize', '%s%%' % str(opts['rsize']),
                      '-autoexpand', '-warning',
                      '%s%%' % str(opts['warning'])]
            if not opts['autoexpand']:
                params.remove('-autoexpand')

            if opts['compression']:
                params.append('-compressed')
            else:
                params.extend(['-grainsize', str(opts['grainsize'])])

        params.extend(['-easytier', easytier])
        return params

    def create_vdisk(self, name, size, units, pool, opts):
        LOG.debug(_('enter: create_vdisk: vdisk %s ') % name)
        params = self._get_vdisk_create_params(opts)
        self.ssh.mkvdisk(name, size, units, pool, opts, params)
        LOG.debug(_('leave: _create_vdisk: volume %s ') % name)

    def get_vdisk_attributes(self, vdisk):
        attrs = self.ssh.lsvdisk(vdisk)
        return attrs

    def is_vdisk_defined(self, vdisk_name):
        """Check if vdisk is defined."""
        attrs = self.get_vdisk_attributes(vdisk_name)
        return attrs is not None

    def _prepare_fc_map(self, fc_map_id, timeout):
        self.ssh.prestartfcmap(fc_map_id)
        mapping_ready = False
        wait_time = 5
        max_retries = (timeout / wait_time) + 1
        for try_number in range(1, max_retries):
            mapping_attrs = self._get_flashcopy_mapping_attributes(fc_map_id)
            if (mapping_attrs is None or
                    'status' not in mapping_attrs):
                break
            if mapping_attrs['status'] == 'prepared':
                mapping_ready = True
                break
            elif mapping_attrs['status'] == 'stopped':
                self.ssh.prestartfcmap(fc_map_id)
            elif mapping_attrs['status'] != 'preparing':
                msg = (_('Unexecpted mapping status %(status)s for mapping'
                         '%(id)s. Attributes: %(attr)s')
                       % {'status': mapping_attrs['status'],
                          'id': fc_map_id,
                          'attr': mapping_attrs})
                LOG.error(msg)
                raise exception.VolumeBackendAPIException(data=msg)
            greenthread.sleep(wait_time)

        if not mapping_ready:
            msg = (_('Mapping %(id)s prepare failed to complete within the'
                     'allotted %(to)d seconds timeout. Terminating.')
                   % {'id': fc_map_id,
                      'to': timeout})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

    def run_flashcopy(self, source, target, timeout, full_copy=True):
        """Create a FlashCopy mapping from the source to the target."""
        LOG.debug(_('enter: run_flashcopy: execute FlashCopy from source '
                    '%(source)s to target %(target)s') %
                  {'source': source, 'target': target})

        fc_map_id = self.ssh.mkfcmap(source, target, full_copy)
        self._prepare_fc_map(fc_map_id, timeout)
        self.ssh.startfcmap(fc_map_id)

        LOG.debug(_('leave: run_flashcopy: FlashCopy started from '
                    '%(source)s to %(target)s') %
                  {'source': source, 'target': target})

    def _get_vdisk_fc_mappings(self, vdisk):
        """Return FlashCopy mappings that this vdisk is associated with."""
        mapping_ids = []
        resp = self.ssh.lsvdiskfcmappings(vdisk)
        for id in resp.select('id'):
            mapping_ids.append(id)
        return mapping_ids

    def _get_flashcopy_mapping_attributes(self, fc_map_id):
        resp = self.ssh.lsfcmap(fc_map_id)
        if not len(resp):
            return None
        return resp[0]

    def _check_vdisk_fc_mappings(self, name, allow_snaps=True):
        """FlashCopy mapping check helper."""
        LOG.debug(_('Loopcall: _check_vdisk_fc_mappings(), vdisk %s') % name)
        mapping_ids = self._get_vdisk_fc_mappings(name)
        wait_for_copy = False
        for map_id in mapping_ids:
            attrs = self._get_flashcopy_mapping_attributes(map_id)
            if not attrs:
                continue
            source = attrs['source_vdisk_name']
            target = attrs['target_vdisk_name']
            copy_rate = attrs['copy_rate']
            status = attrs['status']

            if copy_rate == '0':
                if source == name:
                    # Vdisk with snapshots. Return False if snapshot
                    # not allowed.
                    if not allow_snaps:
                        raise loopingcall.LoopingCallDone(retvalue=False)
                    self.ssh.chfcmap(map_id, copyrate='50', autodel='on')
                    wait_for_copy = True
                else:
                    # A snapshot
                    if target != name:
                        msg = (_('Vdisk %(name)s not involved in '
                                 'mapping %(src)s -> %(tgt)s') %
                               {'name': name, 'src': source, 'tgt': target})
                        LOG.error(msg)
                        raise exception.VolumeDriverException(message=msg)
                    if status in ['copying', 'prepared']:
                        self.ssh.stopfcmap(map_id)
                        # Need to wait for the fcmap to change to
                        # stopped state before remove fcmap
                        wait_for_copy = True
                    elif status in ['stopping', 'preparing']:
                        wait_for_copy = True
                    else:
                        self.ssh.rmfcmap(map_id)
            # Case 4: Copy in progress - wait and will autodelete
            else:
                if status == 'prepared':
                    self.ssh.stopfcmap(map_id)
                    self.ssh.rmfcmap(map_id)
                elif status == 'idle_or_copied':
                    # Prepare failed
                    self.ssh.rmfcmap(map_id)
                else:
                    wait_for_copy = True
        if not wait_for_copy or not len(mapping_ids):
            raise loopingcall.LoopingCallDone(retvalue=True)

    def ensure_vdisk_no_fc_mappings(self, name, allow_snaps=True):
        """Ensure vdisk has no flashcopy mappings."""
        timer = loopingcall.FixedIntervalLoopingCall(
            self._check_vdisk_fc_mappings, name, allow_snaps)
        # Create a timer greenthread. The default volume service heart
        # beat is every 10 seconds. The flashcopy usually takes hours
        # before it finishes. Don't set the sleep interval shorter
        # than the heartbeat. Otherwise volume service heartbeat
        # will not be serviced.
        LOG.debug(_('Calling _ensure_vdisk_no_fc_mappings: vdisk %s')
                  % name)
        ret = timer.start(interval=self.check_fcmapping_interval).wait()
        timer.stop()
        return ret

    def delete_vdisk(self, vdisk, force):
        """Ensures that vdisk is not part of FC mapping and deletes it."""
        LOG.debug(_('enter: delete_vdisk: vdisk %s') % vdisk)
        if not self.is_vdisk_defined(vdisk):
            LOG.info(_('Tried to delete non-existant vdisk %s.') % vdisk)
            return
        self.ensure_vdisk_no_fc_mappings(vdisk)
        self.ssh.rmvdisk(vdisk, force=force)
        LOG.debug(_('leave: delete_vdisk: vdisk %s') % vdisk)

    def create_copy(self, src, tgt, src_id, config, opts, full_copy):
        """Create a new snapshot using FlashCopy."""
        LOG.debug(_('enter: create_copy: snapshot %(src)s to %(tgt)s') %
                  {'tgt': tgt, 'src': src})

        src_attrs = self.get_vdisk_attributes(src)
        if src_attrs is None:
            msg = (_('create_copy: Source vdisk %(src)s (%(src_id)s) '
                     'does not exist') % {'src': src, 'src_id': src_id})
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        src_size = src_attrs['capacity']
        pool = config.storwize_svc_volpool_name
        self.create_vdisk(tgt, src_size, 'b', pool, opts)
        timeout = config.storwize_svc_flashcopy_timeout
        try:
            self.run_flashcopy(src, tgt, timeout, full_copy=full_copy)
        except Exception:
            with excutils.save_and_reraise_exception():
                self.delete_vdisk(tgt, True)

        LOG.debug(_('leave: _create_copy: snapshot %(tgt)s from '
                    'vdisk %(src)s') %
                  {'tgt': tgt, 'src': src})

    def extend_vdisk(self, vdisk, amount):
        self.ssh.expandvdisksize(vdisk, amount)

    def add_vdisk_copy(self, vdisk, dest_pool, volume_type, state, config):
        """Add a vdisk copy in the given pool."""
        resp = self.ssh.lsvdiskcopy(vdisk)
        if len(resp) > 1:
            msg = (_('add_vdisk_copy failed: A copy of volume %s exists. '
                     'Adding another copy would exceed the limit of '
                     '2 copies.') % vdisk)
            raise exception.VolumeDriverException(message=msg)
        orig_copy_id = resp[0].get("copy_id", None)

        if orig_copy_id is None:
            msg = (_('add_vdisk_copy started without a vdisk copy in the '
                     'expected pool.'))
            LOG.error(msg)
            raise exception.VolumeDriverException(message=msg)

        if volume_type is None:
            opts = self.get_vdisk_params(config, state, None)
        else:
            opts = self.get_vdisk_params(config, state, volume_type['id'],
                                         volume_type=volume_type)
        params = self._get_vdisk_create_params(opts)
        new_copy_id = self.ssh.addvdiskcopy(vdisk, dest_pool, params)
        return (orig_copy_id, new_copy_id)

    def is_vdisk_copy_synced(self, vdisk, copy_id):
        sync = self.ssh.lsvdiskcopy(vdisk, copy_id=copy_id)[0]['sync']
        if sync == 'yes':
            return True
        return False

    def rm_vdisk_copy(self, vdisk, copy_id):
        self.ssh.rmvdiskcopy(vdisk, copy_id)

    @staticmethod
    def can_migrate_to_host(host, state):
        if 'location_info' not in host['capabilities']:
            return None
        info = host['capabilities']['location_info']
        try:
            (dest_type, dest_id, dest_pool) = info.split(':')
        except ValueError:
            return None
        if (dest_type != 'StorwizeSVCDriver' or dest_id != state['system_id']):
            return None
        return dest_pool

    def change_vdisk_options(self, vdisk, changes, opts, state):
        if 'warning' in opts:
            opts['warning'] = '%s%%' % str(opts['warning'])
        if 'easytier' in opts:
            opts['easytier'] = 'on' if opts['easytier'] else 'off'
        if 'autoexpand' in opts:
            opts['autoexpand'] = 'on' if opts['autoexpand'] else 'off'

        for key in changes:
            self.ssh.chvdisk(vdisk, ['-' + key, opts[key]])

    def change_vdisk_iogrp(self, vdisk, state, iogrp):
        if state['code_level'] < (6, 4, 0, 0):
            LOG.debug(_('Ignore change IO group as storage code level is '
                        '%(code_level)s, below the required 6.4.0.0') %
                      {'code_level': state['code_level']})
        else:
            self.ssh.movevdisk(vdisk, str(iogrp[0]))
            self.ssh.addvdiskaccess(vdisk, str(iogrp[0]))
            self.ssh.rmvdiskaccess(vdisk, str(iogrp[1]))

    def vdisk_by_uid(self, vdisk_uid):
        """Returns the properties of the vdisk with the specified UID.

        Returns None if no such disk exists.
        """

        vdisks = self.ssh.lsvdisks_from_filter('vdisk_UID', vdisk_uid)

        if len(vdisks) == 0:
            return None

        if len(vdisks) != 1:
            msg = (_('Expected single vdisk returned from lsvdisk when '
                     'filtering on vdisk_UID.  %{count}s were returned.') %
                   {'count': len(vdisks)})
            LOG.error(msg)
            raise exception.VolumeBackendAPIException(data=msg)

        vdisk = vdisks.result[0]

        return self.ssh.lsvdisk(vdisk['name'])

    def is_vdisk_in_use(self, vdisk):
        """Returns True if the specified vdisk is mapped to at least 1 host."""
        resp = self.ssh.lsvdiskhostmap(vdisk)
        return len(resp) != 0

    def rename_vdisk(self, vdisk, new_name):
        self.ssh.chvdisk(vdisk, ['-name', new_name])
