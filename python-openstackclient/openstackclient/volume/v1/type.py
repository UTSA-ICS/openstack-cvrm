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

"""Volume v1 Type action implementations"""

import logging
import six

from cliff import command
from cliff import lister
from cliff import show

from openstackclient.common import parseractions
from openstackclient.common import utils


class CreateVolumeType(show.ShowOne):
    """Create new volume type"""

    log = logging.getLogger(__name__ + '.CreateVolumeType')

    def get_parser(self, prog_name):
        parser = super(CreateVolumeType, self).get_parser(prog_name)
        parser.add_argument(
            'name',
            metavar='<name>',
            help='New volume type name',
        )
        parser.add_argument(
            '--property',
            metavar='<key=value>',
            action=parseractions.KeyValueAction,
            help='Property to add for this volume type '
                 '(repeat option to set multiple properties)',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        volume_client = self.app.client_manager.volume
        volume_type = volume_client.volume_types.create(parsed_args.name)
        volume_type._info.pop('extra_specs')
        if parsed_args.property:
            result = volume_type.set_keys(parsed_args.property)
            volume_type._info.update({'properties': utils.format_dict(result)})

        info = {}
        info.update(volume_type._info)
        return zip(*sorted(six.iteritems(info)))


class DeleteVolumeType(command.Command):
    """Delete volume type"""

    log = logging.getLogger(__name__ + '.DeleteVolumeType')

    def get_parser(self, prog_name):
        parser = super(DeleteVolumeType, self).get_parser(prog_name)
        parser.add_argument(
            'volume_type',
            metavar='<volume-type>',
            help='Name or ID of volume type to delete',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        volume_client = self.app.client_manager.volume
        volume_type_id = utils.find_resource(
            volume_client.volume_types, parsed_args.volume_type).id
        volume_client.volume_types.delete(volume_type_id)
        return


class ListVolumeType(lister.Lister):
    """List volume types"""

    log = logging.getLogger(__name__ + '.ListVolumeType')

    def get_parser(self, prog_name):
        parser = super(ListVolumeType, self).get_parser(prog_name)
        parser.add_argument(
            '--long',
            action='store_true',
            default=False,
            help='List additional fields in output')
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        if parsed_args.long:
            columns = ('ID', 'Name', 'Extra Specs')
            column_headers = ('ID', 'Name', 'Properties')
        else:
            columns = ('ID', 'Name')
            column_headers = columns
        data = self.app.client_manager.volume.volume_types.list()
        return (column_headers,
                (utils.get_item_properties(
                    s, columns,
                    formatters={'Extra Specs': utils.format_dict},
                ) for s in data))


class SetVolumeType(command.Command):
    """Set volume type property"""

    log = logging.getLogger(__name__ + '.SetVolumeType')

    def get_parser(self, prog_name):
        parser = super(SetVolumeType, self).get_parser(prog_name)
        parser.add_argument(
            'volume_type',
            metavar='<volume-type>',
            help='Volume type name or ID to update',
        )
        parser.add_argument(
            '--property',
            metavar='<key=value>',
            action=parseractions.KeyValueAction,
            help='Property to add/change for this volume type '
                 '(repeat option to set multiple properties)',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        volume_client = self.app.client_manager.volume
        volume_type = utils.find_resource(
            volume_client.volume_types, parsed_args.volume_type)

        if parsed_args.property:
            volume_type.set_keys(parsed_args.property)

        return


class UnsetVolumeType(command.Command):
    """Unset volume type property"""

    log = logging.getLogger(__name__ + '.UnsetVolumeType')

    def get_parser(self, prog_name):
        parser = super(UnsetVolumeType, self).get_parser(prog_name)
        parser.add_argument(
            'volume_type',
            metavar='<volume-type>',
            help='Type ID or name to remove',
        )
        parser.add_argument(
            '--property',
            metavar='<key>',
            action='append',
            default=[],
            help='Property key to remove from volume '
                 '(repeat option to remove multiple properties)',
        )
        return parser

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)', parsed_args)
        volume_client = self.app.client_manager.volume
        volume_type = utils.find_resource(
            volume_client.volume_types,
            parsed_args.volume_type,
        )

        if parsed_args.property:
            volume_type.unset_keys(parsed_args.property)
        else:
            self.app.log.error("No changes requested\n")
        return
