# Copyright 2011 OpenStack Foundation
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

"""Keypair management extension."""

import webob
import webob.exc

from nova.api.openstack.compute.schemas.v3 import keypairs
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api import validation
from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common.gettextutils import _


ALIAS = 'keypairs'
authorize = extensions.extension_authorizer('compute', 'v3:' + ALIAS)
soft_authorize = extensions.soft_extension_authorizer('compute', 'v3:' + ALIAS)


class KeypairController(object):

    """Keypair API controller for the OpenStack API."""
    def __init__(self):
        self.api = compute_api.KeypairAPI()

    def _filter_keypair(self, keypair, **attrs):
        clean = {
            'name': keypair.name,
            'public_key': keypair.public_key,
            'fingerprint': keypair.fingerprint,
            }
        for attr in attrs:
            clean[attr] = keypair[attr]
        return clean

    @extensions.expected_errors((400, 409, 413))
    @wsgi.response(201)
    @validation.schema(keypairs.create)
    def create(self, req, body):
        """Create or import keypair.

        Sending name will generate a key and return private_key
        and fingerprint.

        You can send a public_key to add an existing ssh key

        params: keypair object with:
            name (required) - string
            public_key (optional) - string
        """

        context = req.environ['nova.context']
        authorize(context, action='create')

        params = body['keypair']
        name = params['name']

        try:
            if 'public_key' in params:
                keypair = self.api.import_key_pair(context,
                                              context.user_id, name,
                                              params['public_key'])
                keypair = self._filter_keypair(keypair, user_id=True)
            else:
                keypair, private_key = self.api.create_key_pair(
                    context, context.user_id, name)
                keypair = self._filter_keypair(keypair, user_id=True)
                keypair['private_key'] = private_key

            return {'keypair': keypair}

        except exception.KeypairLimitExceeded:
            msg = _("Quota exceeded, too many key pairs.")
            raise webob.exc.HTTPRequestEntityTooLarge(
                        explanation=msg,
                        headers={'Retry-After': 0})
        except exception.InvalidKeypair as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
        except exception.KeyPairExists as exc:
            raise webob.exc.HTTPConflict(explanation=exc.format_message())

    @wsgi.response(204)
    @extensions.expected_errors(404)
    def delete(self, req, id):
        """Delete a keypair with a given name."""
        context = req.environ['nova.context']
        authorize(context, action='delete')
        try:
            self.api.delete_key_pair(context, context.user_id, id)
        except exception.KeypairNotFound:
            raise webob.exc.HTTPNotFound()

    @extensions.expected_errors(404)
    def show(self, req, id):
        """Return data for the given key name."""
        context = req.environ['nova.context']
        authorize(context, action='show')

        try:
            keypair = self.api.get_key_pair(context, context.user_id, id)
        except exception.KeypairNotFound:
            raise webob.exc.HTTPNotFound()
        return {'keypair': self._filter_keypair(keypair)}

    @extensions.expected_errors(())
    def index(self, req):
        """List of keypairs for a user."""
        context = req.environ['nova.context']
        authorize(context, action='index')
        key_pairs = self.api.get_key_pairs(context, context.user_id)
        rval = []
        for key_pair in key_pairs:
            rval.append({'keypair': self._filter_keypair(key_pair)})

        return {'keypairs': rval}


class Controller(wsgi.Controller):

    def _add_key_name(self, req, servers):
        for server in servers:
            db_server = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show'/'detail' methods.
            server['key_name'] = db_server['key_name']

    def _show(self, req, resp_obj):
        if 'server' in resp_obj.obj:
            server = resp_obj.obj['server']
            self._add_key_name(req, [server])

    @wsgi.extends
    def show(self, req, resp_obj, id):
        context = req.environ['nova.context']
        if soft_authorize(context):
            self._show(req, resp_obj)

    @wsgi.extends
    def detail(self, req, resp_obj):
        context = req.environ['nova.context']
        if 'servers' in resp_obj.obj and soft_authorize(context):
            servers = resp_obj.obj['servers']
            self._add_key_name(req, servers)


class Keypairs(extensions.V3APIExtensionBase):
    """Keypair Support."""

    name = "Keypairs"
    alias = ALIAS
    version = 1

    def get_resources(self):
        resources = [
            extensions.ResourceExtension('keypairs',
                                         KeypairController())]
        return resources

    def get_controller_extensions(self):
        controller = Controller()
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]

    # use nova.api.extensions.server.extensions entry point to modify
    # server create kwargs
    def server_create(self, server_dict, create_kwargs):
        create_kwargs['key_name'] = server_dict.get('key_name')
