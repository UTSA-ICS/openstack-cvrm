#   Copyright 2012-2013 OpenStack Foundation
#
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

"""Group action implementations"""

import logging
import six
import sys

from cliff import command
from cliff import lister
from cliff import show
from keystoneclient.openstack.common.apiclient import exceptions as ksc_exc

from openstackclient.common import utils
from openstackclient.i18n import _  # noqa
from openstackclient.identity import common


class AddUserToGroup(command.Command):
    """Add user to group"""

    log = logging.getLogger(__name__ + '.AddUserToGroup')

    def get_parser(self, prog_name):
        parser = super(AddUserToGroup, self).get_parser(prog_name)
        parser.add_argument(
            'group',
            metavar='<group>',
            help='Group name or ID that user will be added to',
        )
        parser.add_argument(
            'user',
            metavar='<user>',
            help='User name or ID to add to group',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity

        user_id = utils.find_resource(identity_client.users,
                                      parsed_args.user).id
        group_id = utils.find_resource(identity_client.groups,
                                       parsed_args.group).id

        try:
            identity_client.users.add_to_group(user_id, group_id)
        except Exception:
            sys.stderr.write("%s not added to group %s\n" %
                             (parsed_args.user, parsed_args.group))
        else:
            sys.stdout.write("%s added to group %s\n" %
                             (parsed_args.user, parsed_args.group))


class CheckUserInGroup(command.Command):
    """Checks that user is in a specific group"""

    log = logging.getLogger(__name__ + '.CheckUserInGroup')

    def get_parser(self, prog_name):
        parser = super(CheckUserInGroup, self).get_parser(prog_name)
        parser.add_argument(
            'group',
            metavar='<group>',
            help='Group name or ID that user will be added to',
        )
        parser.add_argument(
            'user',
            metavar='<user>',
            help='User name or ID to add to group',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity

        user_id = utils.find_resource(identity_client.users,
                                      parsed_args.user).id
        group_id = utils.find_resource(identity_client.groups,
                                       parsed_args.group).id

        try:
            identity_client.users.check_in_group(user_id, group_id)
        except Exception:
            sys.stderr.write("%s not in group %s\n" %
                             (parsed_args.user, parsed_args.group))
        else:
            sys.stdout.write("%s in group %s\n" %
                             (parsed_args.user, parsed_args.group))


class CreateGroup(show.ShowOne):
    """Create group command"""

    log = logging.getLogger(__name__ + '.CreateGroup')

    def get_parser(self, prog_name):
        parser = super(CreateGroup, self).get_parser(prog_name)
        parser.add_argument(
            'name',
            metavar='<group-name>',
            help='New group name')
        parser.add_argument(
            '--description',
            metavar='<group-description>',
            help='New group description')
        parser.add_argument(
            '--domain',
            metavar='<group-domain>',
            help='References the domain ID or name which owns the group')
        parser.add_argument(
            '--or-show',
            action='store_true',
            help=_('Return existing group'),
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity
        if parsed_args.domain:
            domain = common.find_domain(identity_client,
                                        parsed_args.domain).id
        else:
            domain = None

        try:
            group = identity_client.groups.create(
                name=parsed_args.name,
                domain=domain,
                description=parsed_args.description)
        except ksc_exc.Conflict as e:
            if parsed_args.or_show:
                group = utils.find_resource(identity_client.groups,
                                            parsed_args.name,
                                            domain_id=domain)
                self.log.info('Returning existing group %s', group.name)
            else:
                raise e

        group._info.pop('links')
        return zip(*sorted(six.iteritems(group._info)))


class DeleteGroup(command.Command):
    """Delete group command"""

    log = logging.getLogger(__name__ + '.DeleteGroup')

    def get_parser(self, prog_name):
        parser = super(DeleteGroup, self).get_parser(prog_name)
        parser.add_argument(
            'group',
            metavar='<group>',
            help='Name or ID of group to delete')
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity
        group = utils.find_resource(identity_client.groups, parsed_args.group)
        identity_client.groups.delete(group.id)
        return


class ListGroup(lister.Lister):
    """List groups"""

    log = logging.getLogger(__name__ + '.ListGroup')

    def get_parser(self, prog_name):
        parser = super(ListGroup, self).get_parser(prog_name)
        parser.add_argument(
            '--domain',
            metavar='<domain>',
            help='Filter group list by <domain> (name or ID)',
        )
        parser.add_argument(
            '--user',
            metavar='<user>',
            help='List group memberships for <user> (name or ID)',
        )
        parser.add_argument(
            '--long',
            action='store_true',
            default=False,
            help='List additional fields in output',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity

        if parsed_args.domain:
            domain = common.find_domain(identity_client,
                                        parsed_args.domain).id
        else:
            domain = None

        if parsed_args.user:
            user = utils.find_resource(
                identity_client.users,
                parsed_args.user,
            ).id
        else:
            user = None

        # List groups
        if parsed_args.long:
            columns = ('ID', 'Name', 'Domain ID', 'Description')
        else:
            columns = ('ID', 'Name')
        data = identity_client.groups.list(
            domain=domain,
            user=user,
        )

        return (
            columns,
            (utils.get_item_properties(
                s, columns,
                formatters={},
            ) for s in data)
        )


class RemoveUserFromGroup(command.Command):
    """Remove user to group"""

    log = logging.getLogger(__name__ + '.RemoveUserFromGroup')

    def get_parser(self, prog_name):
        parser = super(RemoveUserFromGroup, self).get_parser(prog_name)
        parser.add_argument(
            'group',
            metavar='<group>',
            help='Group name or ID that user will be removed from',
        )
        parser.add_argument(
            'user',
            metavar='<user>',
            help='User name or ID to remove from group',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity

        user_id = utils.find_resource(identity_client.users,
                                      parsed_args.user).id
        group_id = utils.find_resource(identity_client.groups,
                                       parsed_args.group).id

        try:
            identity_client.users.remove_from_group(user_id, group_id)
        except Exception:
            sys.stderr.write("%s not removed from group %s\n" %
                             (parsed_args.user, parsed_args.group))
        else:
            sys.stdout.write("%s removed from group %s\n" %
                             (parsed_args.user, parsed_args.group))


class SetGroup(command.Command):
    """Set group command"""

    log = logging.getLogger(__name__ + '.SetGroup')

    def get_parser(self, prog_name):
        parser = super(SetGroup, self).get_parser(prog_name)
        parser.add_argument(
            'group',
            metavar='<group>',
            help='Name or ID of group to change')
        parser.add_argument(
            '--name',
            metavar='<new-group-name>',
            help='New group name')
        parser.add_argument(
            '--domain',
            metavar='<group-domain>',
            help='New domain name or ID that will now own the group')
        parser.add_argument(
            '--description',
            metavar='<group-description>',
            help='New group description')
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity
        group = utils.find_resource(identity_client.groups, parsed_args.group)
        kwargs = {}
        if parsed_args.name:
            kwargs['name'] = parsed_args.name
        if parsed_args.description:
            kwargs['description'] = parsed_args.description
        if parsed_args.domain:
            kwargs['domain'] = common.find_domain(identity_client,
                                                  parsed_args.domain).id
        if not len(kwargs):
            sys.stderr.write("Group not updated, no arguments present")
            return
        identity_client.groups.update(group.id, **kwargs)
        return


class ShowGroup(show.ShowOne):
    """Show group command"""

    log = logging.getLogger(__name__ + '.ShowGroup')

    def get_parser(self, prog_name):
        parser = super(ShowGroup, self).get_parser(prog_name)
        parser.add_argument(
            'group',
            metavar='<group>',
            help='Name or ID of group to display',
        )
        parser.add_argument(
            '--domain',
            metavar='<domain>',
            help='Domain where group resides (name or ID)',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity

        if parsed_args.domain:
            domain = common.find_domain(identity_client, parsed_args.domain)
            group = utils.find_resource(identity_client.groups,
                                        parsed_args.group,
                                        domain_id=domain.id)
        else:
            group = utils.find_resource(identity_client.groups,
                                        parsed_args.group)

        group._info.pop('links')
        return zip(*sorted(six.iteritems(group._info)))
