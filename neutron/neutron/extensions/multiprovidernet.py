# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright (c) 2013 OpenStack Foundation.
# All rights reserved.
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

import webob.exc

from neutron.api import extensions
from neutron.api.v2 import attributes as attr
from neutron.common import exceptions as qexception
from neutron.extensions import providernet as pnet

SEGMENTS = 'segments'


class SegmentsSetInConjunctionWithProviders(qexception.InvalidInput):
    message = _("Segments and provider values cannot both be set.")


class SegmentsContainDuplicateEntry(qexception.InvalidInput):
    message = _("Duplicate segment entry in request.")


def _convert_and_validate_segments(segments, valid_values=None):
    unique = set()
    for segment in segments:
        unique.add(tuple(segment.iteritems()))
        network_type = segment.get(pnet.NETWORK_TYPE,
                                   attr.ATTR_NOT_SPECIFIED)
        segment[pnet.NETWORK_TYPE] = network_type
        physical_network = segment.get(pnet.PHYSICAL_NETWORK,
                                       attr.ATTR_NOT_SPECIFIED)
        segment[pnet.PHYSICAL_NETWORK] = physical_network
        segmentation_id = segment.get(pnet.SEGMENTATION_ID)
        if segmentation_id:
            segment[pnet.SEGMENTATION_ID] = attr.convert_to_int(
                segmentation_id)
        else:
            segment[pnet.SEGMENTATION_ID] = attr.ATTR_NOT_SPECIFIED
        if len(segment.keys()) != 3:
            msg = (_("Unrecognized attribute(s) '%s'") %
                   ', '.join(set(segment.keys()) -
                             set([pnet.NETWORK_TYPE, pnet.PHYSICAL_NETWORK,
                                  pnet.SEGMENTATION_ID])))
            raise webob.exc.HTTPBadRequest(msg)
    if len(unique) != len(segments):
        raise SegmentsContainDuplicateEntry()


attr.validators['type:convert_segments'] = (
    _convert_and_validate_segments)


EXTENDED_ATTRIBUTES_2_0 = {
    'networks': {
        SEGMENTS: {'allow_post': True, 'allow_put': True,
                   'validate': {'type:convert_segments': None},
                   'convert_list_to': attr.convert_kvp_list_to_dict,
                   'default': attr.ATTR_NOT_SPECIFIED,
                   'enforce_policy': True,
                   'is_visible': True},
    }
}


class Multiprovidernet(extensions.ExtensionDescriptor):
    """Extension class supporting multiple provider networks.

    This class is used by neutron's extension framework to make
    metadata about the multiple provider network extension available to
    clients. No new resources are defined by this extension. Instead,
    the existing network resource's request and response messages are
    extended with attributes in the provider namespace.

    With admin rights, network dictionaries returned will also include
    provider attributes.
    """

    @classmethod
    def get_name(cls):
        return "Multi Provider Network"

    @classmethod
    def get_alias(cls):
        return "multi-provider"

    @classmethod
    def get_description(cls):
        return ("Expose mapping of virtual networks to multiple physical "
                "networks")

    @classmethod
    def get_namespace(cls):
        return "http://docs.openstack.org/ext/multi-provider/api/v1.0"

    @classmethod
    def get_updated(cls):
        return "2013-06-27T10:00:00-00:00"

    def get_extended_resources(self, version):
        if version == "2.0":
            return EXTENDED_ATTRIBUTES_2_0
        else:
            return {}
