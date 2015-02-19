# -*- coding: utf-8 -*-

# Copyright 2013 Metacloud, Inc.
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

"""WSGI Routers for the Assignment service."""

from keystone.assignment import controllers
from keystone.common import router
from keystone.common import wsgi
from keystone import config


class Public(wsgi.ComposableRouter):
    def add_routes(self, mapper):
        tenant_controller = controllers.Tenant()
        mapper.connect('/tenants',
                       controller=tenant_controller,
                       action='get_projects_for_token',
                       conditions=dict(method=['GET']))


class Admin(wsgi.ComposableRouter):
    def add_routes(self, mapper):
        # Tenant Operations
        tenant_controller = controllers.Tenant()
        mapper.connect('/tenants',
                       controller=tenant_controller,
                       action='get_all_projects',
                       conditions=dict(method=['GET']))
        mapper.connect('/tenants/{tenant_id}',
                       controller=tenant_controller,
                       action='get_project',
                       conditions=dict(method=['GET']))

        # Role Operations
        roles_controller = controllers.Role()
        mapper.connect('/tenants/{tenant_id}/users/{user_id}/roles',
                       controller=roles_controller,
                       action='get_user_roles',
                       conditions=dict(method=['GET']))
        mapper.connect('/users/{user_id}/roles',
                       controller=roles_controller,
                       action='get_user_roles',
                       conditions=dict(method=['GET']))


def append_v3_routers(mapper, routers):
    routers.append(
        router.Router(controllers.DomainV3(),
                      'domains', 'domain'))

    project_controller = controllers.ProjectV3()
    routers.append(
        router.Router(project_controller,
                      'projects', 'project'))
    mapper.connect('/users/{user_id}/projects',
                   controller=project_controller,
                   action='list_user_projects',
                   conditions=dict(method=['GET']))

    role_controller = controllers.RoleV3()
    routers.append(router.Router(role_controller, 'roles', 'role'))
    mapper.connect('/projects/{project_id}/users/{user_id}/roles/{role_id}',
                   controller=role_controller,
                   action='create_grant',
                   conditions=dict(method=['PUT']))
    mapper.connect('/projects/{project_id}/groups/{group_id}/roles/{role_id}',
                   controller=role_controller,
                   action='create_grant',
                   conditions=dict(method=['PUT']))
    mapper.connect('/projects/{project_id}/users/{user_id}/roles/{role_id}',
                   controller=role_controller,
                   action='check_grant',
                   conditions=dict(method=['GET', 'HEAD']))
    mapper.connect('/projects/{project_id}/groups/{group_id}/roles/{role_id}',
                   controller=role_controller,
                   action='check_grant',
                   conditions=dict(method=['GET', 'HEAD']))
    mapper.connect('/projects/{project_id}/users/{user_id}/roles',
                   controller=role_controller,
                   action='list_grants',
                   conditions=dict(method=['GET']))
    mapper.connect('/projects/{project_id}/groups/{group_id}/roles',
                   controller=role_controller,
                   action='list_grants',
                   conditions=dict(method=['GET']))
    mapper.connect('/projects/{project_id}/users/{user_id}/roles/{role_id}',
                   controller=role_controller,
                   action='revoke_grant',
                   conditions=dict(method=['DELETE']))
    mapper.connect('/projects/{project_id}/groups/{group_id}/roles/{role_id}',
                   controller=role_controller,
                   action='revoke_grant',
                   conditions=dict(method=['DELETE']))
    mapper.connect('/domains/{domain_id}/users/{user_id}/roles/{role_id}',
                   controller=role_controller,
                   action='create_grant',
                   conditions=dict(method=['PUT']))
    mapper.connect('/domains/{domain_id}/groups/{group_id}/roles/{role_id}',
                   controller=role_controller,
                   action='create_grant',
                   conditions=dict(method=['PUT']))
    mapper.connect('/domains/{domain_id}/users/{user_id}/roles/{role_id}',
                   controller=role_controller,
                   action='check_grant',
                   conditions=dict(method=['GET', 'HEAD']))
    mapper.connect('/domains/{domain_id}/groups/{group_id}/roles/{role_id}',
                   controller=role_controller,
                   action='check_grant',
                   conditions=dict(method=['GET', 'HEAD']))
    mapper.connect('/domains/{domain_id}/users/{user_id}/roles',
                   controller=role_controller,
                   action='list_grants',
                   conditions=dict(method=['GET']))
    mapper.connect('/domains/{domain_id}/groups/{group_id}/roles',
                   controller=role_controller,
                   action='list_grants',
                   conditions=dict(method=['GET']))
    mapper.connect('/domains/{domain_id}/users/{user_id}/roles/{role_id}',
                   controller=role_controller,
                   action='revoke_grant',
                   conditions=dict(method=['DELETE']))
    mapper.connect('/domains/{domain_id}/groups/{group_id}/roles/{role_id}',
                   controller=role_controller,
                   action='revoke_grant',
                   conditions=dict(method=['DELETE']))

    if config.CONF.os_inherit.enabled:
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/users/{user_id}'
                        '/roles/{role_id}/inherited_to_projects'),
                       controller=role_controller,
                       action='create_grant',
                       conditions=dict(method=['PUT']))
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/groups/{group_id}'
                        '/roles/{role_id}/inherited_to_projects'),
                       controller=role_controller,
                       action='create_grant',
                       conditions=dict(method=['PUT']))
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/users/{user_id}'
                        '/roles/{role_id}/inherited_to_projects'),
                       controller=role_controller,
                       action='check_grant',
                       conditions=dict(method=['GET', 'HEAD']))
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/groups/{group_id}'
                        '/roles/{role_id}/inherited_to_projects'),
                       controller=role_controller,
                       action='check_grant',
                       conditions=dict(method=['GET', 'HEAD']))
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/users/{user_id}'
                        '/roles/inherited_to_projects'),
                       controller=role_controller,
                       action='list_grants',
                       conditions=dict(method=['GET']))
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/groups/{group_id}'
                        '/roles/inherited_to_projects'),
                       controller=role_controller,
                       action='list_grants',
                       conditions=dict(method=['GET']))
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/users/{user_id}'
                        '/roles/{role_id}/inherited_to_projects'),
                       controller=role_controller,
                       action='revoke_grant',
                       conditions=dict(method=['DELETE']))
        mapper.connect(('/OS-INHERIT/domains/{domain_id}/groups/{group_id}'
                        '/roles/{role_id}/inherited_to_projects'),
                       controller=role_controller,
                       action='revoke_grant',
                       conditions=dict(method=['DELETE']))
    routers.append(
        router.Router(controllers.RoleAssignmentV3(),
                      'role_assignments', 'role_assignment'))
