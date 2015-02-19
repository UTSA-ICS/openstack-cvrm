# Copyright 2011 OpenStack Foundation
# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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

"""RequestContext: context for requests that persist through all of cinder."""

import copy
import uuid

from cinder.openstack.common import local
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder import policy


LOG = logging.getLogger(__name__)


def generate_request_id():
    return 'req-' + str(uuid.uuid4())


class RequestContext(object):
    """Security context and request information.

    Represents the user taking a given action within the system.

    """
    user_idt_format = '{user} {tenant} {domain} {user_domain} {p_domain}'

    def __init__(self, user_id, project_id, is_admin=None, read_deleted="no",
                 roles=None, project_name=None, remote_address=None,
                 timestamp=None, request_id=None, auth_token=None,
                 overwrite=True, quota_class=None, service_catalog=None,
                 domain=None, user_domain=None, project_domain=None,
                 **kwargs):
        """Initialize RequestContext.

        :param read_deleted: 'no' indicates deleted records are hidden, 'yes'
            indicates deleted records are visible, 'only' indicates that
            *only* deleted records are visible.

        :param overwrite: Set to False to ensure that the greenthread local
            copy of the index is not overwritten.

        :param kwargs: Extra arguments that might be present, but we ignore
            because they possibly came in from older rpc messages.
        """
        if kwargs:
            LOG.warn(_('Arguments dropped when creating context: %s') %
                     str(kwargs))

        self.user_id = user_id
        self.project_id = project_id
        self.domain = domain
        self.user_domain = user_domain
        self.project_domain = project_domain
        self.roles = roles or []
        self.project_name = project_name
        self.is_admin = is_admin
        if self.is_admin is None:
            self.is_admin = policy.check_is_admin(self.roles)
        elif self.is_admin and 'admin' not in self.roles:
            self.roles.append('admin')
        self.read_deleted = read_deleted
        self.remote_address = remote_address
        if not timestamp:
            timestamp = timeutils.utcnow()
        if isinstance(timestamp, basestring):
            timestamp = timeutils.parse_strtime(timestamp)
        self.timestamp = timestamp
        if not request_id:
            request_id = generate_request_id()
        self.request_id = request_id
        self.auth_token = auth_token
        self.quota_class = quota_class
        if overwrite or not hasattr(local.store, 'context'):
            self.update_store()
        self.quota_committed = False

        if service_catalog:
            # Only include required parts of service_catalog
            self.service_catalog = [s for s in service_catalog
                                    if s.get('type') in ('compute',)]
        else:
            # if list is empty or none
            self.service_catalog = []

    def _get_read_deleted(self):
        return self._read_deleted

    def _set_read_deleted(self, read_deleted):
        if read_deleted not in ('no', 'yes', 'only'):
            raise ValueError(_("read_deleted can only be one of 'no', "
                               "'yes' or 'only', not %r") % read_deleted)
        self._read_deleted = read_deleted

    def _del_read_deleted(self):
        del self._read_deleted

    read_deleted = property(_get_read_deleted, _set_read_deleted,
                            _del_read_deleted)

    def update_store(self):
        local.store.context = self

    def to_dict(self):
        user_idt = (
            self.user_idt_format.format(user=self.user or '-',
                                        tenant=self.tenant or '-',
                                        domain=self.domain or '-',
                                        user_domain=self.user_domain or '-',
                                        p_domain=self.project_domain or '-'))

        return {'user_id': self.user_id,
                'project_id': self.project_id,
                'project_name': self.project_name,
                'domain': self.domain,
                'user_domain': self.user_domain,
                'project_domain': self.project_domain,
                'is_admin': self.is_admin,
                'read_deleted': self.read_deleted,
                'roles': self.roles,
                'remote_address': self.remote_address,
                'timestamp': timeutils.strtime(self.timestamp),
                'request_id': self.request_id,
                'auth_token': self.auth_token,
                'quota_class': self.quota_class,
                'service_catalog': self.service_catalog,
                'tenant': self.tenant,
                'user': self.user,
                'user_identity': user_idt}

    @classmethod
    def from_dict(cls, values):
        return cls(**values)

    def elevated(self, read_deleted=None, overwrite=False):
        """Return a version of this context with admin flag set."""
        context = copy.copy(self)
        context.is_admin = True

        if 'admin' not in context.roles:
            context.roles.append('admin')

        if read_deleted is not None:
            context.read_deleted = read_deleted

        return context

    def deepcopy(self):
        return copy.deepcopy(self)

    # NOTE(sirp): the openstack/common version of RequestContext uses
    # tenant/user whereas the Cinder version uses project_id/user_id. We need
    # this shim in order to use context-aware code from openstack/common, like
    # logging, until we make the switch to using openstack/common's version of
    # RequestContext.
    @property
    def tenant(self):
        return self.project_id

    @property
    def user(self):
        return self.user_id


def get_admin_context(read_deleted="no"):
    return RequestContext(user_id=None,
                          project_id=None,
                          is_admin=True,
                          read_deleted=read_deleted,
                          overwrite=False)
