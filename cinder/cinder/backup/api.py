# Copyright (C) 2012 Hewlett-Packard Development Company, L.P.
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
Handles all requests relating to the volume backups service.
"""


from eventlet import greenthread

from oslo.config import cfg

from cinder.backup import rpcapi as backup_rpcapi
from cinder import context
from cinder.db import base
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import utils

import cinder.policy
import cinder.volume

CONF = cfg.CONF
LOG = logging.getLogger(__name__)


def check_policy(context, action):
    target = {
        'project_id': context.project_id,
        'user_id': context.user_id,
    }
    _action = 'backup:%s' % action
    cinder.policy.enforce(context, _action, target)


class API(base.Base):
    """API for interacting with the volume backup manager."""

    def __init__(self, db_driver=None):
        self.backup_rpcapi = backup_rpcapi.BackupAPI()
        self.volume_api = cinder.volume.API()
        super(API, self).__init__(db_driver)

    def get(self, context, backup_id):
        check_policy(context, 'get')
        rv = self.db.backup_get(context, backup_id)
        return dict(rv.iteritems())

    def delete(self, context, backup_id):
        """Make the RPC call to delete a volume backup."""
        check_policy(context, 'delete')
        backup = self.get(context, backup_id)
        if backup['status'] not in ['available', 'error']:
            msg = _('Backup status must be available or error')
            raise exception.InvalidBackup(reason=msg)

        self.db.backup_update(context, backup_id, {'status': 'deleting'})
        self.backup_rpcapi.delete_backup(context,
                                         backup['host'],
                                         backup['id'])

    # TODO(moorehef): Add support for search_opts, discarded atm
    def get_all(self, context, search_opts=None):
        if search_opts is None:
            search_opts = {}
        check_policy(context, 'get_all')
        if context.is_admin:
            backups = self.db.backup_get_all(context)
        else:
            backups = self.db.backup_get_all_by_project(context,
                                                        context.project_id)

        return backups

    def _is_backup_service_enabled(self, volume, volume_host):
        """Check if there is a backup service available."""
        topic = CONF.backup_topic
        ctxt = context.get_admin_context()
        services = self.db.service_get_all_by_topic(ctxt, topic)
        for srv in services:
            if (srv['availability_zone'] == volume['availability_zone'] and
                    srv['host'] == volume_host and not srv['disabled'] and
                    utils.service_is_up(srv)):
                return True
        return False

    def _list_backup_services(self):
        """List all enabled backup services.

        :returns: list -- hosts for services that are enabled for backup.
        """
        topic = CONF.backup_topic
        ctxt = context.get_admin_context()
        services = self.db.service_get_all_by_topic(ctxt, topic)
        return [srv['host'] for srv in services if not srv['disabled']]

    def create(self, context, name, description, volume_id,
               container, availability_zone=None):
        """Make the RPC call to create a volume backup."""
        check_policy(context, 'create')
        volume = self.volume_api.get(context, volume_id)
        if volume['status'] != "available":
            msg = _('Volume to be backed up must be available')
            raise exception.InvalidVolume(reason=msg)
        volume_host = volume['host'].partition('@')[0]
        if not self._is_backup_service_enabled(volume, volume_host):
            raise exception.ServiceNotFound(service_id='cinder-backup')

        self.db.volume_update(context, volume_id, {'status': 'backing-up'})

        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'display_name': name,
                   'display_description': description,
                   'volume_id': volume_id,
                   'status': 'creating',
                   'container': container,
                   'size': volume['size'],
                   'host': volume_host, }

        backup = self.db.backup_create(context, options)

        #TODO(DuncanT): In future, when we have a generic local attach,
        #               this can go via the scheduler, which enables
        #               better load balancing and isolation of services
        self.backup_rpcapi.create_backup(context,
                                         backup['host'],
                                         backup['id'],
                                         volume_id)

        return backup

    def restore(self, context, backup_id, volume_id=None):
        """Make the RPC call to restore a volume backup."""
        check_policy(context, 'restore')
        backup = self.get(context, backup_id)
        if backup['status'] != 'available':
            msg = _('Backup status must be available')
            raise exception.InvalidBackup(reason=msg)

        size = backup['size']
        if size is None:
            msg = _('Backup to be restored has invalid size')
            raise exception.InvalidBackup(reason=msg)

        # Create a volume if none specified. If a volume is specified check
        # it is large enough for the backup
        if volume_id is None:
            name = 'restore_backup_%s' % backup_id
            description = 'auto-created_from_restore_from_backup'

            LOG.audit(_("Creating volume of %(size)s GB for restore of "
                        "backup %(backup_id)s"),
                      {'size': size, 'backup_id': backup_id},
                      context=context)
            volume = self.volume_api.create(context, size, name, description)
            volume_id = volume['id']

            while True:
                volume = self.volume_api.get(context, volume_id)
                if volume['status'] != 'creating':
                    break
                greenthread.sleep(1)
        else:
            volume = self.volume_api.get(context, volume_id)

        if volume['status'] != "available":
            msg = _('Volume to be restored to must be available')
            raise exception.InvalidVolume(reason=msg)

        LOG.debug('Checking backup size %s against volume size %s',
                  size, volume['size'])
        if size > volume['size']:
            msg = (_('volume size %(volume_size)d is too small to restore '
                     'backup of size %(size)d.') %
                   {'volume_size': volume['size'], 'size': size})
            raise exception.InvalidVolume(reason=msg)

        LOG.audit(_("Overwriting volume %(volume_id)s with restore of "
                    "backup %(backup_id)s"),
                  {'volume_id': volume_id, 'backup_id': backup_id},
                  context=context)

        # Setting the status here rather than setting at start and unrolling
        # for each error condition, it should be a very small window
        self.db.backup_update(context, backup_id, {'status': 'restoring'})
        self.db.volume_update(context, volume_id, {'status':
                                                   'restoring-backup'})
        self.backup_rpcapi.restore_backup(context,
                                          backup['host'],
                                          backup['id'],
                                          volume_id)

        d = {'backup_id': backup_id,
             'volume_id': volume_id, }

        return d

    def export_record(self, context, backup_id):
        """Make the RPC call to export a volume backup.

        Call backup manager to execute backup export.

        :param context: running context
        :param backup_id: backup id to export
        :returns: dictionary -- a description of how to import the backup
        :returns: contains 'backup_url' and 'backup_service'
        :raises: InvalidBackup
        """
        check_policy(context, 'backup-export')
        backup = self.get(context, backup_id)
        if backup['status'] != 'available':
            msg = (_('Backup status must be available and not %s.') %
                   backup['status'])
            raise exception.InvalidBackup(reason=msg)

        LOG.debug("Calling RPCAPI with context: "
                  "%(ctx)s, host: %(host)s, backup: %(id)s.",
                  {'ctx': context,
                   'host': backup['host'],
                   'id': backup['id']})
        export_data = self.backup_rpcapi.export_record(context,
                                                       backup['host'],
                                                       backup['id'])

        return export_data

    def import_record(self, context, backup_service, backup_url):
        """Make the RPC call to import a volume backup.

        :param context: running context
        :param backup_service: backup service name
        :param backup_url: backup description to be used by the backup driver
        :raises: InvalidBackup
        :raises: ServiceNotFound
        """
        check_policy(context, 'backup-import')

        # NOTE(ronenkat): since we don't have a backup-scheduler
        # we need to find a host that support the backup service
        # that was used to create the backup.
        # We  send it to the first backup service host, and the backup manager
        # on that host will forward it to other hosts on the hosts list if it
        # cannot support correct service itself.
        hosts = self._list_backup_services()
        if len(hosts) == 0:
            raise exception.ServiceNotFound(service_id=backup_service)

        options = {'user_id': context.user_id,
                   'project_id': context.project_id,
                   'volume_id': '0000-0000-0000-0000',
                   'status': 'creating', }
        backup = self.db.backup_create(context, options)
        first_host = hosts.pop()
        self.backup_rpcapi.import_record(context,
                                         first_host,
                                         backup['id'],
                                         backup_service,
                                         backup_url,
                                         hosts)

        return backup
