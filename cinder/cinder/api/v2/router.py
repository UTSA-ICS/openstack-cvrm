# Copyright 2011 OpenStack Foundation
# Copyright 2011 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
# All Rights Reserved.
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

"""
WSGI middleware for OpenStack Volume API.
"""

from cinder.api import extensions
import cinder.api.openstack
from cinder.api.v2 import limits
from cinder.api.v2 import snapshot_metadata
from cinder.api.v2 import snapshots
from cinder.api.v2 import types
from cinder.api.v2 import volume_metadata
from cinder.api.v2 import volumes
from cinder.api.v2 import attribute
from cinder.api import versions
from cinder.openstack.common import log as logging


LOG = logging.getLogger(__name__)


class APIRouter(cinder.api.openstack.APIRouter):
    """Routes requests on the API to the appropriate controller and method."""
    ExtensionManager = extensions.ExtensionManager

    def _setup_routes(self, mapper, ext_mgr):
        self.resources['versions'] = versions.create_resource()
        mapper.connect("versions", "/",
                       controller=self.resources['versions'],
                       action='show')

        mapper.redirect("", "/")

        self.resources['volumes'] = volumes.create_resource(ext_mgr)
        mapper.resource("volume", "volumes",
                        controller=self.resources['volumes'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})

        self.resources['types'] = types.create_resource()
        mapper.resource("type", "types",
                        controller=self.resources['types'])

        self.resources['snapshots'] = snapshots.create_resource(ext_mgr)
        mapper.resource("snapshot", "snapshots",
                        controller=self.resources['snapshots'],
                        collection={'detail': 'GET'},
                        member={'action': 'POST'})

        self.resources['limits'] = limits.create_resource()
        mapper.resource("limit", "limits",
                        controller=self.resources['limits'])

        self.resources['snapshot_metadata'] = \
            snapshot_metadata.create_resource()
        snapshot_metadata_controller = self.resources['snapshot_metadata']

        mapper.resource("snapshot_metadata", "metadata",
                        controller=snapshot_metadata_controller,
                        parent_resource=dict(member_name='snapshot',
                                             collection_name='snapshots'))

        mapper.connect("metadata",
                       "/{project_id}/snapshots/{snapshot_id}/metadata",
                       controller=snapshot_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})

        self.resources['volume_metadata'] = \
            volume_metadata.create_resource()
        volume_metadata_controller = self.resources['volume_metadata']

        mapper.resource("volume_metadata", "metadata",
                        controller=volume_metadata_controller,
                        parent_resource=dict(member_name='volume',
                                             collection_name='volumes'))

        mapper.connect("metadata",
                       "/{project_id}/volumes/{volume_id}/metadata",
                       controller=volume_metadata_controller,
                       action='update_all',
                       conditions={"method": ['PUT']})


        self.resources['attribute'] = \
            attribute.create_resource()
        attribute_controller = self.resources['attribute']

        mapper.resource("attribute", "attribute",
                        controller=attribute_controller
			)
        mapper.connect("attribute",
                       "/{project_id}/os-attributes",
                       controller=attribute_controller,
                       action='create',
                       conditions={"method": ['POST']})
