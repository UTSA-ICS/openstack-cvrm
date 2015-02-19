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

"""Identity v3 Domain action implementations"""

import logging
import six
import sys

from cliff import command
from cliff import lister
from cliff import show
from keystoneclient.openstack.common.apiclient import exceptions as ksc_exc

from openstackclient.common import utils
from openstackclient.i18n import _  # noqa


class CreateDomain(show.ShowOne):
    """Create domain command"""

    log = logging.getLogger(__name__ + '.CreateDomain')

    def get_parser(self, prog_name):
        parser = super(CreateDomain, self).get_parser(prog_name)
        parser.add_argument(
            'name',
            metavar='<domain-name>',
            help='New domain name',
        )
        parser.add_argument(
            '--description',
            metavar='<domain-description>',
            help='New domain description',
        )
        enable_group = parser.add_mutually_exclusive_group()
        enable_group.add_argument(
            '--enable',
            dest='enabled',
            action='store_true',
            default=True,
            help='Enable domain')
        enable_group.add_argument(
            '--disable',
            dest='enabled',
            action='store_false',
            help='Disable domain')
        parser.add_argument(
            '--or-show',
            action='store_true',
            help=_('Return existing domain'),
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity

        try:
            domain = identity_client.domains.create(
                name=parsed_args.name,
                description=parsed_args.description,
                enabled=parsed_args.enabled,
            )
        except ksc_exc.Conflict as e:
            if parsed_args.or_show:
                domain = utils.find_resource(identity_client.domains,
                                             parsed_args.name)
                self.log.info('Returning existing domain %s', domain.name)
            else:
                raise e

        domain._info.pop('links')
        return zip(*sorted(six.iteritems(domain._info)))


class DeleteDomain(command.Command):
    """Delete domain command"""

    log = logging.getLogger(__name__ + '.DeleteDomain')

    def get_parser(self, prog_name):
        parser = super(DeleteDomain, self).get_parser(prog_name)
        parser.add_argument(
            'domain',
            metavar='<domain>',
            help='Name or ID of domain to delete',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity
        domain = utils.find_resource(identity_client.domains,
                                     parsed_args.domain)
        identity_client.domains.delete(domain.id)
        return


class ListDomain(lister.Lister):
    """List domain command"""

    log = logging.getLogger(__name__ + '.ListDomain')

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        columns = ('ID', 'Name', 'Enabled', 'Description')
        data = self.app.client_manager.identity.domains.list()
        return (columns,
                (utils.get_item_properties(
                    s, columns,
                    formatters={},
                ) for s in data))


class SetDomain(command.Command):
    """Set domain command"""

    log = logging.getLogger(__name__ + '.SetDomain')

    def get_parser(self, prog_name):
        parser = super(SetDomain, self).get_parser(prog_name)
        parser.add_argument(
            'domain',
            metavar='<domain>',
            help='Name or ID of domain to change',
        )
        parser.add_argument(
            '--name',
            metavar='<new-domain-name>',
            help='New domain name',
        )
        parser.add_argument(
            '--description',
            metavar='<domain-description>',
            help='New domain description',
        )
        enable_group = parser.add_mutually_exclusive_group()
        enable_group.add_argument(
            '--enable',
            dest='enabled',
            action='store_true',
            help='Enable domain (default)',
        )
        enable_group.add_argument(
            '--disable',
            dest='disabled',
            action='store_true',
            help='Disable domain',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity
        domain = utils.find_resource(identity_client.domains,
                                     parsed_args.domain)
        kwargs = {}
        if parsed_args.name:
            kwargs['name'] = parsed_args.name
        if parsed_args.description:
            kwargs['description'] = parsed_args.description
        if parsed_args.enabled:
            kwargs['enabled'] = True
        if parsed_args.disabled:
            kwargs['enabled'] = False

        if not kwargs:
            sys.stdout.write("Domain not updated, no arguments present")
            return
        identity_client.domains.update(domain.id, **kwargs)
        return


class ShowDomain(show.ShowOne):
    """Show domain command"""

    log = logging.getLogger(__name__ + '.ShowDomain')

    def get_parser(self, prog_name):
        parser = super(ShowDomain, self).get_parser(prog_name)
        parser.add_argument(
            'domain',
            metavar='<domain>',
            help='Name or ID of domain to display',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        identity_client = self.app.client_manager.identity
        domain = utils.find_resource(identity_client.domains,
                                     parsed_args.domain)

        domain._info.pop('links')
        return zip(*sorted(six.iteritems(domain._info)))
