# Copyright 2012 OpenStack Foundation
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

"""Main entry point into the Policy service."""

import abc

import six

from keystone.common import dependency
from keystone.common import manager
from keystone import config
from keystone import exception


CONF = config.CONF


@dependency.provider('policy_api')
class Manager(manager.Manager):
    """Default pivot point for the Policy backend.

    See :mod:`keystone.common.manager.Manager` for more details on how this
    dynamically calls the backend.

    """

    def __init__(self):
        super(Manager, self).__init__(CONF.policy.driver)

    def get_policy(self, policy_id):
        try:
            return self.driver.get_policy(policy_id)
        except exception.NotFound:
            raise exception.PolicyNotFound(policy_id=policy_id)

    def update_policy(self, policy_id, policy):
        if 'id' in policy and policy_id != policy['id']:
            raise exception.ValidationError('Cannot change policy ID')
        try:
            return self.driver.update_policy(policy_id, policy)
        except exception.NotFound:
            raise exception.PolicyNotFound(policy_id=policy_id)

    @manager.response_truncated
    def list_policies(self, hints=None):
        # NOTE(henry-nash): Since the advantage of filtering or list limiting
        # of policies at the driver level is minimal, we leave this to the
        # caller.
        return self.driver.list_policies()

    def delete_policy(self, policy_id):
        try:
            return self.driver.delete_policy(policy_id)
        except exception.NotFound:
            raise exception.PolicyNotFound(policy_id=policy_id)


@six.add_metaclass(abc.ABCMeta)
class Driver(object):

    def _get_list_limit(self):
        return CONF.policy.list_limit or CONF.list_limit

    @abc.abstractmethod
    def enforce(self, context, credentials, action, target):
        """Verify that a user is authorized to perform action.

        For more information on a full implementation of this see:
        `keystone.common.policy.enforce`.
        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def create_policy(self, policy_id, policy):
        """Store a policy blob.

        :raises: keystone.exception.Conflict

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def list_policies(self):
        """List all policies."""
        raise exception.NotImplemented()

    @abc.abstractmethod
    def get_policy(self, policy_id):
        """Retrieve a specific policy blob.

        :raises: keystone.exception.PolicyNotFound

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def update_policy(self, policy_id, policy):
        """Update a policy blob.

        :raises: keystone.exception.PolicyNotFound

        """
        raise exception.NotImplemented()

    @abc.abstractmethod
    def delete_policy(self, policy_id):
        """Remove a policy blob.

        :raises: keystone.exception.PolicyNotFound

        """
        raise exception.NotImplemented()
