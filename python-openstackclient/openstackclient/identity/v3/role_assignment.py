#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#

"""Identity v3 Assignment action implementations """

import logging

from cliff import lister

from openstackclient.common import utils


class ListRoleAssignment(lister.Lister):
    """Lists role assignments according to the given filters"""

    log = logging.getLogger(__name__ + '.ListRoleAssignment')

    def get_parser(self, prog_name):
        parser = super(ListRoleAssignment, self).get_parser(prog_name)
        parser.add_argument(
            '--effective',
            action="store_true",
            default=False,
            help='Returns only effective role assignments',
        )
        parser.add_argument(
            '--role',
            metavar='<role>',
            help='Name or ID of role to filter',
        )
        user_or_group = parser.add_mutually_exclusive_group()
        user_or_group.add_argument(
            '--user',
            metavar='<user>',
            help='Name or ID of user to filter',
        )
        user_or_group.add_argument(
            '--group',
            metavar='<group>',
            help='Name or ID of group to filter',
        )
        domain_or_project = parser.add_mutually_exclusive_group()
        domain_or_project.add_argument(
            '--domain',
            metavar='<domain>',
            help='Name or ID of domain to filter',
        )
        domain_or_project.add_argument(
            '--project',
            metavar='<project>',
            help='Name or ID of project to filter',
        )

        return parser

    def _as_tuple(self, assignment):
        return (assignment.role, assignment.user, assignment.group,
                assignment.project, assignment.domain)

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)' % parsed_args)
        identity_client = self.app.client_manager.identity

        role = None
        if parsed_args.role:
            role = utils.find_resource(
                identity_client.roles,
                parsed_args.role,
            )

        user = None
        if parsed_args.user:
            user = utils.find_resource(
                identity_client.users,
                parsed_args.user,
            )

        domain = None
        if parsed_args.domain:
            domain = utils.find_resource(
                identity_client.domains,
                parsed_args.domain,
            )

        project = None
        if parsed_args.project:
            project = utils.find_resource(
                identity_client.projects,
                parsed_args.project,
            )

        group = None
        if parsed_args.group:
            group = utils.find_resource(
                identity_client.groups,
                parsed_args.group,
            )

        effective = True if parsed_args.effective else False
        self.log.debug('take_action(%s)' % parsed_args)
        columns = ('Role', 'User', 'Group', 'Project', 'Domain')
        data = identity_client.role_assignments.list(
            domain=domain,
            user=user,
            group=group,
            project=project,
            role=role,
            effective=effective)

        data_parsed = []
        for assignment in data:
            # Removing the extra "scope" layer in the assignment json
            scope = assignment.scope
            if 'project' in scope:
                setattr(assignment, 'project', scope['project']['id'])
                assignment.domain = ''
            elif 'domain' in scope:
                setattr(assignment, 'domain', scope['domain']['id'])
                assignment.project = ''

            else:
                assignment.domain = ''
                assignment.project = ''

            del assignment.scope

            if hasattr(assignment, 'user'):
                setattr(assignment, 'user', assignment.user['id'])
                assignment.group = ''
            elif hasattr(assignment, 'group'):
                setattr(assignment, 'group', assignment.group['id'])
                assignment.user = ''
            else:
                assignment.user = ''
                assignment.group = ''

            if hasattr(assignment, 'role'):
                setattr(assignment, 'role', assignment.role['id'])
            else:
                assignment.role = ''

            # Creating a tuple from data object fields
            # (including the blank ones)
            data_parsed.append(self._as_tuple(assignment))

        return columns, tuple(data_parsed)
