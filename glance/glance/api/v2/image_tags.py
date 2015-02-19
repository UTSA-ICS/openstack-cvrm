# Copyright 2012 OpenStack Foundation
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

import webob.exc

from glance.api import policy
from glance.common import exception
from glance.common import utils
from glance.common import wsgi
import glance.db
import glance.gateway
import glance.notifier
import glance.store


class Controller(object):
    def __init__(self, db_api=None, policy_enforcer=None, notifier=None,
                 store_api=None):
        self.db_api = db_api or glance.db.get_api()
        self.policy = policy_enforcer or policy.Enforcer()
        self.notifier = notifier or glance.notifier.Notifier()
        self.store_api = store_api or glance.store
        self.gateway = glance.gateway.Gateway(self.db_api, self.store_api,
                                              self.notifier, self.policy)

    @utils.mutating
    def update(self, req, image_id, tag_value):
        image_repo = self.gateway.get_repo(req.context)
        try:
            image = image_repo.get(image_id)
            image.tags.add(tag_value)
            image_repo.save(image)
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.msg)
        except exception.Forbidden as e:
            raise webob.exc.HTTPForbidden(explanation=e.msg)
        except exception.ImageTagLimitExceeded as e:
            raise webob.exc.HTTPRequestEntityTooLarge(explanation=e.msg)

    @utils.mutating
    def delete(self, req, image_id, tag_value):
        image_repo = self.gateway.get_repo(req.context)
        try:
            image = image_repo.get(image_id)
            if tag_value not in image.tags:
                raise webob.exc.HTTPNotFound()
            image.tags.remove(tag_value)
            image_repo.save(image)
        except exception.NotFound as e:
            raise webob.exc.HTTPNotFound(explanation=e.msg)
        except exception.Forbidden as e:
            raise webob.exc.HTTPForbidden(explanation=e.msg)


class ResponseSerializer(wsgi.JSONResponseSerializer):
    def update(self, response, result):
        response.status_int = 204

    def delete(self, response, result):
        response.status_int = 204


def create_resource():
    """Images resource factory method"""
    serializer = ResponseSerializer()
    controller = Controller()
    return wsgi.Resource(controller, serializer=serializer)
