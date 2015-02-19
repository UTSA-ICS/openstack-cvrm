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

"""Workflow Logic the Identity service."""

import functools
import inspect
import six
import uuid

from keystone.assignment import controllers as assignment_controllers
from keystone.common import controller
from keystone.common import dependency
from keystone import config
from keystone import exception
from keystone.openstack.common.gettextutils import _
from keystone.openstack.common import log
from keystone.openstack.common import versionutils


CONF = config.CONF
LOG = log.getLogger(__name__)


class DeprecatedMeta(type):
    """Metaclass that ensures that the correct methods on the deprecated
    classes are reported as deprecated on call.
    """
    @staticmethod
    def moved_to_assignment(class_name):
        # NOTE(morganfainberg): wrapper for versionutils.deprecated decorator
        # with some values populated specifically for the migration for
        # controllers from identity to assignment.
        def inner(f):
            subst = {'cls_name': class_name, 'meth_name': f.__name__}
            what = 'identity.controllers.%(cls_name)s.%(meth_name)s' % subst
            favor = 'assignment.controllers.%(cls_name)s.%(meth_name)s' % subst

            deprecated = versionutils.deprecated(
                versionutils.deprecated.ICEHOUSE,
                what=what,
                in_favor_of=favor,
                remove_in=+1)
            return deprecated(f)
        return inner

    @staticmethod
    def _is_wrappable(item):
        # NOTE(morganfainberg): Wrapping non-callables, non-methods, and
        # builtins is not the point of the deprecation warnings. Simple test
        # to ensure the item is one of the types that should be wrapped.
        if (callable(item) and
                inspect.ismethod(item) and
                not inspect.isbuiltin(item)):
            return True
        return False

    def __new__(mcs, class_name, bases, namespace):
        def get_attribute(self, item):
            # NOTE(morganfainberg): This implementation of __getattribute__
            # is automatically added to any classes using the DeprecatedMeta
            # metaclass. This will apply the moved_to_assignment wrapper to
            # method calls (inherited or direct).
            attr = super(bases[0], self).__getattribute__(item)
            if DeprecatedMeta._is_wrappable(attr):
                return DeprecatedMeta.moved_to_assignment(class_name)(attr)
            return attr

        namespace['__getattribute__'] = get_attribute
        return type.__new__(mcs, class_name, bases, namespace)

    def __getattribute__(cls, item):
        # NOTE(morganfainberg): This implementation of __getattribute__ catches
        # non-instantiated calls to @classmethods.
        attr = type.__getattribute__(cls, item)
        if DeprecatedMeta._is_wrappable(attr):
            if (issubclass(cls, controller.V3Controller) and
                    DeprecatedMeta._is_wrappable(attr)):
                attr = DeprecatedMeta.moved_to_assignment(cls.__name__)(attr)
        return attr


@dependency.requires('assignment_api', 'identity_api')
class User(controller.V2Controller):

    @controller.v2_deprecated
    def get_user(self, context, user_id):
        self.assert_admin(context)
        ref = self.identity_api.get_user(user_id)
        return {'user': self.v3_to_v2_user(ref)}

    @controller.v2_deprecated
    def get_users(self, context):
        # NOTE(termie): i can't imagine that this really wants all the data
        #               about every single user in the system...
        if 'name' in context['query_string']:
            return self.get_user_by_name(
                context, context['query_string'].get('name'))

        self.assert_admin(context)
        user_list = self.identity_api.list_users()
        return {'users': self.v3_to_v2_user(user_list)}

    @controller.v2_deprecated
    def get_user_by_name(self, context, user_name):
        self.assert_admin(context)
        ref = self.identity_api.get_user_by_name(
            user_name, CONF.identity.default_domain_id)
        return {'user': self.v3_to_v2_user(ref)}

    # CRUD extension
    @controller.v2_deprecated
    def create_user(self, context, user):
        user = self._normalize_OSKSADM_password_on_request(user)
        user = self.normalize_username_in_request(user)
        user = self._normalize_dict(user)
        self.assert_admin(context)

        if 'name' not in user or not user['name']:
            msg = _('Name field is required and cannot be empty')
            raise exception.ValidationError(message=msg)
        if 'enabled' in user and not isinstance(user['enabled'], bool):
            msg = _('Enabled field must be a boolean')
            raise exception.ValidationError(message=msg)

        default_project_id = user.pop('tenantId', None)
        if default_project_id is not None:
            # Check to see if the project is valid before moving on.
            self.assignment_api.get_project(default_project_id)
            user['default_project_id'] = default_project_id

        user_id = uuid.uuid4().hex
        user_ref = self._normalize_domain_id(context, user.copy())
        user_ref['id'] = user_id
        new_user_ref = self.v3_to_v2_user(
            self.identity_api.create_user(user_id, user_ref))

        if default_project_id is not None:
            self.assignment_api.add_user_to_project(default_project_id,
                                                    user_id)
        return {'user': new_user_ref}

    @controller.v2_deprecated
    def update_user(self, context, user_id, user):
        # NOTE(termie): this is really more of a patch than a put
        user = self.normalize_username_in_request(user)
        self.assert_admin(context)

        if 'enabled' in user and not isinstance(user['enabled'], bool):
            msg = _('Enabled field should be a boolean')
            raise exception.ValidationError(message=msg)

        default_project_id = user.pop('tenantId', None)
        if default_project_id is not None:
            user['default_project_id'] = default_project_id

        old_user_ref = self.v3_to_v2_user(
            self.identity_api.get_user(user_id))

        # Check whether a tenant is being added or changed for the user.
        # Catch the case where the tenant is being changed for a user and also
        # where a user previously had no tenant but a tenant is now being
        # added for the user.
        if (('tenantId' in old_user_ref and
                old_user_ref['tenantId'] != default_project_id and
                default_project_id is not None) or
            ('tenantId' not in old_user_ref and
                default_project_id is not None)):
            # Make sure the new project actually exists before we perform the
            # user update.
            self.assignment_api.get_project(default_project_id)

        user_ref = self.v3_to_v2_user(
            self.identity_api.update_user(user_id, user))

        # If 'tenantId' is in either ref, we might need to add or remove the
        # user from a project.
        if 'tenantId' in user_ref or 'tenantId' in old_user_ref:
            if user_ref['tenantId'] != old_user_ref.get('tenantId'):
                if old_user_ref.get('tenantId'):
                    try:
                        member_role_id = config.CONF.member_role_id
                        self.assignment_api.remove_role_from_user_and_project(
                            user_id, old_user_ref['tenantId'], member_role_id)
                    except exception.NotFound:
                        # NOTE(morganfainberg): This is not a critical error it
                        # just means that the user cannot be removed from the
                        # old tenant.  This could occur if roles aren't found
                        # or if the project is invalid or if there are no roles
                        # for the user on that project.
                        msg = _('Unable to remove user %(user)s from '
                                '%(tenant)s.')
                        LOG.warning(msg, {'user': user_id,
                                          'tenant': old_user_ref['tenantId']})

                if user_ref['tenantId']:
                    try:
                        self.assignment_api.add_user_to_project(
                            user_ref['tenantId'], user_id)
                    except exception.Conflict:
                        # We are already a member of that tenant
                        pass
                    except exception.NotFound:
                        # NOTE(morganfainberg): Log this and move on. This is
                        # not the end of the world if we can't add the user to
                        # the appropriate tenant. Most of the time this means
                        # that the project is invalid or roles are some how
                        # incorrect.  This shouldn't prevent the return of the
                        # new ref.
                        msg = _('Unable to add user %(user)s to %(tenant)s.')
                        LOG.warning(msg, {'user': user_id,
                                          'tenant': user_ref['tenantId']})

        return {'user': user_ref}

    @controller.v2_deprecated
    def delete_user(self, context, user_id):
        self.assert_admin(context)
        self.identity_api.delete_user(user_id)

    @controller.v2_deprecated
    def set_user_enabled(self, context, user_id, user):
        return self.update_user(context, user_id, user)

    @controller.v2_deprecated
    def set_user_password(self, context, user_id, user):
        user = self._normalize_OSKSADM_password_on_request(user)
        return self.update_user(context, user_id, user)

    @staticmethod
    def _normalize_OSKSADM_password_on_request(ref):
        """Sets the password from the OS-KSADM Admin Extension.

        The OS-KSADM Admin Extension documentation says that
        `OS-KSADM:password` can be used in place of `password`.

        """
        if 'OS-KSADM:password' in ref:
            ref['password'] = ref.pop('OS-KSADM:password')
        return ref


@dependency.requires('identity_api')
class UserV3(controller.V3Controller):
    collection_name = 'users'
    member_name = 'user'

    def __init__(self):
        super(UserV3, self).__init__()
        self.get_member_from_driver = self.identity_api.get_user

    def _check_user_and_group_protection(self, context, prep_info,
                                         user_id, group_id):
        ref = {}
        ref['user'] = self.identity_api.get_user(user_id)
        ref['group'] = self.identity_api.get_group(group_id)
        self.check_protection(context, prep_info, ref)

    @controller.protected()
    def create_user(self, context, user):
        self._require_attribute(user, 'name')

        ref = self._assign_unique_id(self._normalize_dict(user))
        ref = self._normalize_domain_id(context, ref)
        ref = self.identity_api.create_user(ref['id'], ref)
        return UserV3.wrap_member(context, ref)

    @controller.filterprotected('domain_id', 'enabled', 'name')
    def list_users(self, context, filters):
        hints = UserV3.build_driver_hints(context, filters)
        refs = self.identity_api.list_users(
            domain_scope=self._get_domain_id_for_request(context),
            hints=hints)
        return UserV3.wrap_collection(context, refs, hints=hints)

    @controller.filterprotected('domain_id', 'enabled', 'name')
    def list_users_in_group(self, context, filters, group_id):
        hints = UserV3.build_driver_hints(context, filters)
        refs = self.identity_api.list_users_in_group(
            group_id,
            domain_scope=self._get_domain_id_for_request(context),
            hints=hints)
        return UserV3.wrap_collection(context, refs, hints=hints)

    @controller.protected()
    def get_user(self, context, user_id):
        ref = self.identity_api.get_user(
            user_id,
            domain_scope=self._get_domain_id_for_request(context))
        return UserV3.wrap_member(context, ref)

    def _update_user(self, context, user_id, user, domain_scope):
        self._require_matching_id(user_id, user)
        self._require_matching_domain_id(
            user_id, user,
            functools.partial(self.identity_api.get_user,
                              domain_scope=domain_scope))
        ref = self.identity_api.update_user(
            user_id, user, domain_scope=domain_scope)
        return UserV3.wrap_member(context, ref)

    @controller.protected()
    def update_user(self, context, user_id, user):
        domain_scope = self._get_domain_id_for_request(context)
        return self._update_user(context, user_id, user, domain_scope)

    @controller.protected(callback=_check_user_and_group_protection)
    def add_user_to_group(self, context, user_id, group_id):
        self.identity_api.add_user_to_group(
            user_id, group_id,
            domain_scope=self._get_domain_id_for_request(context))

    @controller.protected(callback=_check_user_and_group_protection)
    def check_user_in_group(self, context, user_id, group_id):
        self.identity_api.check_user_in_group(
            user_id, group_id,
            domain_scope=self._get_domain_id_for_request(context))

    @controller.protected(callback=_check_user_and_group_protection)
    def remove_user_from_group(self, context, user_id, group_id):
        self.identity_api.remove_user_from_group(
            user_id, group_id,
            domain_scope=self._get_domain_id_for_request(context))

    @controller.protected()
    def delete_user(self, context, user_id):
        # Make sure any tokens are marked as deleted
        domain_id = self._get_domain_id_for_request(context)
        # Finally delete the user itself - the backend is
        # responsible for deleting any role assignments related
        # to this user
        return self.identity_api.delete_user(user_id, domain_scope=domain_id)

    @controller.protected()
    def change_password(self, context, user_id, user):
        original_password = user.get('original_password')
        if original_password is None:
            raise exception.ValidationError(target='user',
                                            attribute='original_password')

        password = user.get('password')
        if password is None:
            raise exception.ValidationError(target='user',
                                            attribute='password')

        domain_scope = self._get_domain_id_for_request(context)
        try:
            self.identity_api.change_password(
                context, user_id, original_password, password, domain_scope)
        except AssertionError:
            raise exception.Unauthorized()


@dependency.requires('identity_api')
class GroupV3(controller.V3Controller):
    collection_name = 'groups'
    member_name = 'group'

    def __init__(self):
        super(GroupV3, self).__init__()
        self.get_member_from_driver = self.identity_api.get_group

    @controller.protected()
    def create_group(self, context, group):
        self._require_attribute(group, 'name')

        ref = self._assign_unique_id(self._normalize_dict(group))
        ref = self._normalize_domain_id(context, ref)
        ref = self.identity_api.create_group(ref['id'], ref)
        return GroupV3.wrap_member(context, ref)

    @controller.filterprotected('domain_id', 'name')
    def list_groups(self, context, filters):
        hints = GroupV3.build_driver_hints(context, filters)
        refs = self.identity_api.list_groups(
            domain_scope=self._get_domain_id_for_request(context),
            hints=hints)
        return GroupV3.wrap_collection(context, refs, hints=hints)

    @controller.filterprotected('name')
    def list_groups_for_user(self, context, filters, user_id):
        hints = GroupV3.build_driver_hints(context, filters)
        refs = self.identity_api.list_groups_for_user(
            user_id,
            domain_scope=self._get_domain_id_for_request(context),
            hints=hints)
        return GroupV3.wrap_collection(context, refs, hints=hints)

    @controller.protected()
    def get_group(self, context, group_id):
        ref = self.identity_api.get_group(
            group_id,
            domain_scope=self._get_domain_id_for_request(context))
        return GroupV3.wrap_member(context, ref)

    @controller.protected()
    def update_group(self, context, group_id, group):
        self._require_matching_id(group_id, group)
        domain_scope = self._get_domain_id_for_request(context)
        self._require_matching_domain_id(
            group_id, group,
            functools.partial(self.identity_api.get_group,
                              domain_scope=domain_scope))
        ref = self.identity_api.update_group(
            group_id, group,
            domain_scope=domain_scope)
        return GroupV3.wrap_member(context, ref)

    @controller.protected()
    def delete_group(self, context, group_id):
        domain_id = self._get_domain_id_for_request(context)
        self.identity_api.delete_group(group_id, domain_scope=domain_id)


# TODO(morganfainberg): Remove proxy compat classes once Icehouse is released.
@six.add_metaclass(DeprecatedMeta)
class Tenant(assignment_controllers.Tenant):
    pass


@six.add_metaclass(DeprecatedMeta)
class Role(assignment_controllers.Role):
    pass


@six.add_metaclass(DeprecatedMeta)
class DomainV3(assignment_controllers.DomainV3):
    pass


@six.add_metaclass(DeprecatedMeta)
class ProjectV3(assignment_controllers.ProjectV3):
    pass


@six.add_metaclass(DeprecatedMeta)
class RoleV3(assignment_controllers.RoleV3):
    pass


@six.add_metaclass(DeprecatedMeta)
class RoleAssignmentV3(assignment_controllers.RoleAssignmentV3):
    pass
