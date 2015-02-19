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

"""Scope management extension."""
import traceback
import webob
import webob.exc

from nova.api.openstack.compute import servers
from nova.api.openstack import extensions
from nova.api.openstack import wsgi
from nova.api.openstack import xmlutil
from nova.compute import api as compute_api
from nova import exception
from nova.openstack.common.gettextutils import _


authorize = extensions.extension_authorizer('compute', 'scopes')
soft_authorize = extensions.soft_extension_authorizer('compute', 'scopes')


class ScopeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        return xmlutil.MasterTemplate(xmlutil.make_flat_dict('scope'), 1)


class ScopesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('scopes')
        elem = xmlutil.make_flat_dict('scope', selector='scopes',
                                      subselector='scope')
        root.append(elem)

        return xmlutil.MasterTemplate(root, 1)


class ScopeController(object):

    """Scope API controller for the OpenStack API."""
    def __init__(self):
        self.api = compute_api.ScopeAPI()
	self.attribute_api = compute_api.AttributeAPI()

    def _filter_scope(self, scope, **attrs):
        clean = {
            'name': scope.name,
            'public_key': scope.public_key,
            'fingerprint': scope.fingerprint,
            }
        for attr in attrs:
            clean[attr] = scope[attr]
        return clean

    @wsgi.serializers(xml=ScopeTemplate)
    def create(self, req, body):
        """Create or import scope.

        Sending name will generate a key and return private_key
        and fingerprint.

        You can send a public_key to add an existing ssh key

        params: scope object with:
            name (required) - string
            public_key (optional) - string
        """

        context = req.environ['nova.context']
        authorize(context, action='create')

 	try:
            params = body['scope']
            name = params['name']
            value = params['value']
	    print name,value
	    attribute_list =  self.attribute_api.list(context)
	    attname = [att.name for att in attribute_list]
        except KeyError:
            msg = _("Invalid request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)
	
	if name in attname:
	   scope=self.api.create_scope(context,name,value)
	   #return {'scope',scope}
	   #print "yes"
        else:    
	    msg = _("Attribute Not there")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        #try:
              #attribute=self.api.create_attribute(context, name)

              #return {'attribute': attribute}

        #except exception.InvalidAttribute as exc:
            #raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
        '''
        try:
            if 'public_key' in params:
                scope = self.api.import_key_pair(context,
                                              context.user_id, name,
                                              params['public_key'])
                scope = self._filter_scope(scope, user_id=True)
            else:
                scope, private_key = self.api.create_key_pair(
                    context, context.user_id, name)
                scope = self._filter_scope(scope, user_id=True)
                scope['private_key'] = private_key

            return {'scope': scope}

        except exception.ScopeLimitExceeded:
            msg = _("Quota exceeded, too many key pairs.")
            raise webob.exc.HTTPRequestEntityTooLarge(
                        explanation=msg,
                        headers={'Retry-After': 0})
        except exception.InvalidScope as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
        except exception.ScopeExists as exc:
            raise webob.exc.HTTPConflict(explanation=exc.format_message())
        '''
    def delete(self, req, id):
        """Delete a scope with a given name."""
        context = req.environ['nova.context']
        authorize(context, action='delete')
        try:
            self.api.delete_key_pair(context, context.user_id, id)
        except exception.ScopeNotFound:
            raise webob.exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=ScopeTemplate)
    def show(self, req, id):
        """Return data for the given key name."""
        context = req.environ['nova.context']
        authorize(context, action='show')

        try:
            scope = self.api.get_key_pair(context, context.user_id, id)
        except exception.ScopeNotFound:
            raise webob.exc.HTTPNotFound()
        return {'scope': scope}

    
    @wsgi.serializers(xml=ScopeTemplate)
    def index(self, req):
        """List of attributes for a user."""
        context = req.environ['nova.context']
        #authorize(context, action='create')
        try:
              scopelist=self.api.list(context)
              scope = []
              for sc in scopelist:
                scope.append({'id': sc.id,
			   'name': sc.name,
                           'value': sc.value})
              print scope
              return {'scope': scope}


        except exception.InvalidScope as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
    

class ServerKeyNameTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('server')
        root.set('key_name', 'key_name')
        return xmlutil.SlaveTemplate(root, 1)


class ServersKeyNameTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('servers')
        elem = xmlutil.SubTemplateElement(root, 'server', selector='servers')
        elem.set('key_name', 'key_name')
        return xmlutil.SlaveTemplate(root, 1)


class Controller(servers.Controller):

    def _add_key_name(self, req, servers):
        for server in servers:
            db_server = req.get_db_instance(server['id'])
            # server['id'] is guaranteed to be in the cache due to
            # the core API adding it in its 'show'/'detail' methods.
            server['key_name'] = db_server['key_name']

    def _show(self, req, resp_obj):
        if 'server' in resp_obj.obj:
            resp_obj.attach(xml=ServerKeyNameTemplate())
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
            resp_obj.attach(xml=ServersKeyNameTemplate())
            servers = resp_obj.obj['servers']
            self._add_key_name(req, servers)


class Scopes(extensions.ExtensionDescriptor):
    """Scope Support."""
    traceback.print_stack()
    name = "Scopes"
    alias = "os-scopes"
    namespace = "http://docs.openstack.org/compute/ext/scopes/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
                'os-scopes',
                ScopeController())
        resources.append(res)
        return resources

    def get_controller_extensions(self):
        controller = Controller(self.ext_mgr)
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
