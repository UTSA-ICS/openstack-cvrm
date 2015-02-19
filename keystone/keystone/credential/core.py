# Copyright 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

"""Main entry point into the Credentials service."""

import abc

import six

from keystone.common import dependency
from keystone.common import manager
from keystone import config
from keystone import exception
from keystone.openstack.common.gettextutils import _
from keystone.openstack.common import log


CONF = config.CONF

LOG = log.getLogger(__name__)


@dependency.provider('credential_api')
class Manager(manager.Manager):
    """Default pivot point for the Credential backend.

    See :mod:`keystone.common.manager.Manager` for more details on how this
    dynamically calls the backend.

    """

    def __init__(self):
        super(Manager, self).__init__(CONF.credential.driver)


@six.add_metaclass(abc.ABCMeta)
class Driver(object):
    # credential crud

    @abc.abstractmethod
    def create_credential(self, credential_id, credential):
        """Creates a new credential.

        :raises: keystone.exception.Conflict

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def list_credentials(self, **filters):
        """List all credentials in the system applying filters.

        :returns: a list of credential_refs or an empty list.

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def get_credential(self, credential_id):
        """Get a credential by ID.

        :returns: credential_ref
        :raises: keystone.exception.CredentialNotFound

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def update_credential(self, credential_id, credential):
        """Updates an existing credential.

        :raises: keystone.exception.CredentialNotFound,
                 keystone.exception.Conflict

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def delete_credential(self, credential_id):
        """Deletes an existing credential.

        :raises: keystone.exception.CredentialNotFound

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def delete_credentials_for_project(self, project_id):
        """Deletes all credentials for a project."""
        self._delete_credentials(lambda cr: cr['project_id'] == project_id)

    @abc.abstractmethod
    def delete_credentials_for_user(self, user_id):
        """Deletes all credentials for a user."""
        self._delete_credentials(lambda cr: cr['user_id'] == user_id)

    def _delete_credentials(self, match_fn):
        """Do the actual credential deletion work (default implementation).

        :param match_fn: function that takes a credential dict as the
                         parameter and returns true or false if the
                         identifier matches the credential dict.
        """
        for cr in self.list_credentials():
            if match_fn(cr):
                try:
                    self.credential_api.delete_credential(cr['id'])
                except exception.CredentialNotFound:
                    LOG.debug(_('Deletion of credential is not required: %s'),
                              cr['id'])
