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
from __future__ import absolute_import
import uuid

import ldap
import ldap.filter

from keystone import clean
from keystone.common import dependency
from keystone.common import driver_hints
from keystone.common import ldap as common_ldap
from keystone.common import models
from keystone.common import utils
from keystone import config
from keystone import exception
from keystone import identity
from keystone.openstack.common.gettextutils import _
from keystone.openstack.common import log


CONF = config.CONF
LOG = log.getLogger(__name__)


@dependency.requires('assignment_api')
class Identity(identity.Driver):
    def __init__(self, conf=None):
        super(Identity, self).__init__()
        if conf is None:
            conf = CONF
        self.user = UserApi(conf)
        self.group = GroupApi(conf)

    def default_assignment_driver(self):
        return "keystone.assignment.backends.ldap.Assignment"

    def is_domain_aware(self):
        return False

    # Identity interface

    def authenticate(self, user_id, password):
        try:
            user_ref = self._get_user(user_id)
        except exception.UserNotFound:
            raise AssertionError(_('Invalid user / password'))
        if not user_id or not password:
            raise AssertionError(_('Invalid user / password'))
        conn = None
        try:
            conn = self.user.get_connection(self.user._id_to_dn(user_id),
                                            password)
            if not conn:
                raise AssertionError(_('Invalid user / password'))
        except Exception:
            raise AssertionError(_('Invalid user / password'))
        finally:
            if conn:
                conn.unbind_s()
        return identity.filter_user(user_ref)

    def _get_user(self, user_id):
        return self.user.get(user_id)

    def get_user(self, user_id):
        return identity.filter_user(self._get_user(user_id))

    def list_users(self, hints):
        return self.user.get_all_filtered()

    def get_user_by_name(self, user_name, domain_id):
        # domain_id will already have been handled in the Manager layer,
        # parameter left in so this matches the Driver specification
        return identity.filter_user(self.user.get_by_name(user_name))

    # CRUD
    def create_user(self, user_id, user):
        self.user.check_allow_create()
        user_ref = self.user.create(user)
        return identity.filter_user(user_ref)

    def update_user(self, user_id, user):
        self.user.check_allow_update()
        if 'id' in user and user['id'] != user_id:
            raise exception.ValidationError(_('Cannot change user ID'))
        old_obj = self.user.get(user_id)
        if 'name' in user and old_obj.get('name') != user['name']:
            raise exception.Conflict(_('Cannot change user name'))

        user = utils.hash_ldap_user_password(user)
        if self.user.enabled_mask:
            self.user.mask_enabled_attribute(user)
        self.user.update(user_id, user, old_obj)
        return self.user.get_filtered(user_id)

    def delete_user(self, user_id):
        self.user.check_allow_delete()
        self.assignment_api.delete_user(user_id)
        user_dn = self.user._id_to_dn(user_id)
        groups = self.group.list_user_groups(user_dn)
        for group in groups:
            self.group.remove_user(user_dn, group['id'], user_id)

        user = self.user.get(user_id)
        if hasattr(user, 'tenant_id'):
            self.project.remove_user(user.tenant_id,
                                     self.user._id_to_dn(user_id))
        self.user.delete(user_id)

    def create_group(self, group_id, group):
        self.group.check_allow_create()
        group['name'] = clean.group_name(group['name'])
        return self.group.create(group)

    def get_group(self, group_id):
        return self.group.get(group_id)

    def update_group(self, group_id, group):
        self.group.check_allow_update()
        if 'name' in group:
            group['name'] = clean.group_name(group['name'])
        return self.group.update(group_id, group)

    def delete_group(self, group_id):
        self.group.check_allow_delete()
        return self.group.delete(group_id)

    def add_user_to_group(self, user_id, group_id):
        self.get_user(user_id)
        self.get_group(group_id)
        user_dn = self.user._id_to_dn(user_id)
        self.group.add_user(user_dn, group_id, user_id)

    def remove_user_from_group(self, user_id, group_id):
        self.get_user(user_id)
        self.get_group(group_id)
        user_dn = self.user._id_to_dn(user_id)
        self.group.remove_user(user_dn, group_id, user_id)

    def list_groups_for_user(self, user_id, hints):
        self.get_user(user_id)
        user_dn = self.user._id_to_dn(user_id)
        return self.group.list_user_groups(user_dn)

    def list_groups(self, hints):
        return self.group.get_all()

    def list_users_in_group(self, group_id, hints):
        self.get_group(group_id)
        users = []
        for user_dn in self.group.list_group_users(group_id):
            user_id = self.user._dn_to_id(user_dn)
            try:
                users.append(self.user.get_filtered(user_id))
            except exception.UserNotFound:
                LOG.debug(_("Group member '%(user_dn)s' not found in"
                            " '%(group_id)s'. The user should be removed"
                            " from the group. The user will be ignored."),
                          dict(user_dn=user_dn, group_id=group_id))
        return users

    def check_user_in_group(self, user_id, group_id):
        self.get_user(user_id)
        self.get_group(group_id)
        user_refs = self.list_users_in_group(group_id, driver_hints.Hints())
        found = False
        for x in user_refs:
            if x['id'] == user_id:
                found = True
                break
        if not found:
            raise exception.NotFound(_('User not found in group'))


# TODO(termie): turn this into a data object and move logic to driver
class UserApi(common_ldap.EnabledEmuMixIn, common_ldap.BaseLdap):
    DEFAULT_OU = 'ou=Users'
    DEFAULT_STRUCTURAL_CLASSES = ['person']
    DEFAULT_ID_ATTR = 'cn'
    DEFAULT_OBJECTCLASS = 'inetOrgPerson'
    NotFound = exception.UserNotFound
    options_name = 'user'
    attribute_options_names = {'password': 'pass',
                               'email': 'mail',
                               'name': 'name',
                               'enabled': 'enabled',
                               'default_project_id': 'default_project_id'}
    immutable_attrs = ['id']

    model = models.User

    def __init__(self, conf):
        super(UserApi, self).__init__(conf)
        self.enabled_mask = conf.ldap.user_enabled_mask
        self.enabled_default = conf.ldap.user_enabled_default

    def _ldap_res_to_model(self, res):
        obj = super(UserApi, self)._ldap_res_to_model(res)
        if self.enabled_mask != 0:
            enabled = int(obj.get('enabled', self.enabled_default))
            obj['enabled'] = ((enabled & self.enabled_mask) !=
                              self.enabled_mask)
        return obj

    def mask_enabled_attribute(self, values):
        value = values['enabled']
        values.setdefault('enabled_nomask', int(self.enabled_default))
        if value != ((values['enabled_nomask'] & self.enabled_mask) !=
                     self.enabled_mask):
            values['enabled_nomask'] ^= self.enabled_mask
        values['enabled'] = values['enabled_nomask']
        del values['enabled_nomask']

    def create(self, values):
        values = utils.hash_ldap_user_password(values)
        if self.enabled_mask:
            orig_enabled = values['enabled']
            self.mask_enabled_attribute(values)
        values = super(UserApi, self).create(values)
        if self.enabled_mask:
            values['enabled'] = orig_enabled
        return values

    def check_password(self, user_id, password):
        user = self.get(user_id)
        return utils.check_password(password, user.password)

    def get_filtered(self, user_id):
        user = self.get(user_id)
        return identity.filter_user(user)

    def get_all_filtered(self):
        return [identity.filter_user(user) for user in self.get_all()]


class GroupApi(common_ldap.BaseLdap):
    DEFAULT_OU = 'ou=UserGroups'
    DEFAULT_STRUCTURAL_CLASSES = []
    DEFAULT_OBJECTCLASS = 'groupOfNames'
    DEFAULT_ID_ATTR = 'cn'
    DEFAULT_MEMBER_ATTRIBUTE = 'member'
    NotFound = exception.GroupNotFound
    options_name = 'group'
    attribute_options_names = {'description': 'desc',
                               'name': 'name'}
    immutable_attrs = ['name']
    model = models.Group

    def __init__(self, conf):
        super(GroupApi, self).__init__(conf)
        self.member_attribute = (getattr(conf.ldap, 'group_member_attribute')
                                 or self.DEFAULT_MEMBER_ATTRIBUTE)

    def create(self, values):
        data = values.copy()
        if data.get('id') is None:
            data['id'] = uuid.uuid4().hex
        if 'description' in data and data['description'] in ['', None]:
            data.pop('description')
        return super(GroupApi, self).create(data)

    def delete(self, group_id):
        if self.subtree_delete_enabled:
            super(GroupApi, self).deleteTree(group_id)
        else:
            # TODO(spzala): this is only placeholder for group and domain
            # role support which will be added under bug 1101287

            query = '(objectClass=%s)' % self.object_class
            dn = None
            dn = self._id_to_dn(group_id)
            if dn:
                try:
                    conn = self.get_connection()
                    roles = conn.search_s(dn, ldap.SCOPE_ONELEVEL,
                                          query, ['%s' % '1.1'])
                    for role_dn, _ in roles:
                        conn.delete_s(role_dn)
                except ldap.NO_SUCH_OBJECT:
                    pass
                finally:
                    conn.unbind_s()
            super(GroupApi, self).delete(group_id)

    def update(self, group_id, values):
        old_obj = self.get(group_id)
        return super(GroupApi, self).update(group_id, values, old_obj)

    def add_user(self, user_dn, group_id, user_id):
        conn = self.get_connection()
        try:
            conn.modify_s(
                self._id_to_dn(group_id),
                [(ldap.MOD_ADD,
                  self.member_attribute,
                  user_dn)])
        except ldap.TYPE_OR_VALUE_EXISTS:
            raise exception.Conflict(_(
                'User %(user_id)s is already a member of group %(group_id)s') %
                {'user_id': user_id, 'group_id': group_id})
        finally:
            conn.unbind_s()

    def remove_user(self, user_dn, group_id, user_id):
        conn = self.get_connection()
        try:
            conn.modify_s(
                self._id_to_dn(group_id),
                [(ldap.MOD_DELETE,
                  self.member_attribute,
                  user_dn)])
        except ldap.NO_SUCH_ATTRIBUTE:
            raise exception.UserNotFound(user_id=user_id)
        finally:
            conn.unbind_s()

    def list_user_groups(self, user_dn):
        """Return a list of groups for which the user is a member."""

        user_dn_esc = ldap.filter.escape_filter_chars(user_dn)
        query = '(&(objectClass=%s)(%s=%s)%s)' % (self.object_class,
                                                  self.member_attribute,
                                                  user_dn_esc,
                                                  self.ldap_filter or '')
        memberships = self.get_all(query)
        return memberships

    def list_group_users(self, group_id):
        """Return a list of user dns which are members of a group."""
        query = '(objectClass=%s)' % self.object_class
        conn = self.get_connection()
        group_dn = self._id_to_dn(group_id)
        try:
            attrs = conn.search_s(group_dn,
                                  ldap.SCOPE_BASE,
                                  query, ['%s' % self.member_attribute])
        except ldap.NO_SUCH_OBJECT:
            return []
        finally:
            conn.unbind_s()
        users = []
        for dn, member in attrs:
            user_dns = member.get(self.member_attribute, [])
            for user_dn in user_dns:
                if self.use_dumb_member and user_dn == self.dumb_member:
                    continue
                users.append(user_dn)
        return users
