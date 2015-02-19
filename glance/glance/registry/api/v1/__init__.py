# Copyright 2010-2011 OpenStack Foundation
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

from glance.common import wsgi
from glance.registry.api.v1 import images
from glance.registry.api.v1 import members


def init(mapper):
        images_resource = images.create_resource()

        mapper.connect("/",
                       controller=images_resource,
                       action="index")
        mapper.connect("/images",
                       controller=images_resource,
                       action="index",
                       conditions={'method': ['GET']})
        mapper.connect("/images",
                       controller=images_resource,
                       action="create",
                       conditions={'method': ['POST']})
        mapper.connect("/images/detail",
                       controller=images_resource,
                       action="detail",
                       conditions={'method': ['GET']})
        mapper.connect("/images/{id}",
                       controller=images_resource,
                       action="show",
                       conditions=dict(method=["GET"]))
        mapper.connect("/images/{id}",
                       controller=images_resource,
                       action="update",
                       conditions=dict(method=["PUT"]))
        mapper.connect("/images/{id}",
                       controller=images_resource,
                       action="delete",
                       conditions=dict(method=["DELETE"]))

        members_resource = members.create_resource()

        mapper.connect("/images/{image_id}/members",
                       controller=members_resource,
                       action="index",
                       conditions={'method': ['GET']})
        mapper.connect("/images/{image_id}/members",
                       controller=members_resource,
                       action="create",
                       conditions={'method': ['POST']})
        mapper.connect("/images/{image_id}/members",
                       controller=members_resource,
                       action="update_all",
                       conditions=dict(method=["PUT"]))
        mapper.connect("/images/{image_id}/members/{id}",
                       controller=members_resource,
                       action="show",
                       conditions={'method': ['GET']})
        mapper.connect("/images/{image_id}/members/{id}",
                       controller=members_resource,
                       action="update",
                       conditions={'method': ['PUT']})
        mapper.connect("/images/{image_id}/members/{id}",
                       controller=members_resource,
                       action="delete",
                       conditions={'method': ['DELETE']})
        mapper.connect("/shared-images/{id}",
                       controller=members_resource,
                       action="index_shared_images")


class API(wsgi.Router):
    """WSGI entry point for all Registry requests."""

    def __init__(self, mapper):
        mapper = mapper or wsgi.APIMapper()

        init(mapper)

        super(API, self).__init__(mapper)
