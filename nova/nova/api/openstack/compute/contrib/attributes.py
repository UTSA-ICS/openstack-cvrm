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

"""Attribute management extension."""
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


authorize = extensions.extension_authorizer('compute', 'attributes')
soft_authorize = extensions.soft_extension_authorizer('compute', 'attributes')


class AttributeTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        return xmlutil.MasterTemplate(xmlutil.make_flat_dict('attribute'), 1)


class AttributesTemplate(xmlutil.TemplateBuilder):
    def construct(self):
        root = xmlutil.TemplateElement('attributes')
        elem = xmlutil.make_flat_dict('attribute', selector='attributes',
                                      subselector='attribute')
        root.append(elem)

        return xmlutil.MasterTemplate(root, 1)


class AttributeController(object):

    """Attribute API controller for the OpenStack API."""
    def __init__(self):
        self.api = compute_api.AttributeAPI()

    def _filter_attribute(self, attribute, **attrs):
        clean = {
            'name': attribute.name,
            'public_key': attribute.public_key,
            'fingerprint': attribute.fingerprint,
            }
        for attr in attrs:
            clean[attr] = attribute[attr]
        return clean

    @wsgi.serializers(xml=AttributeTemplate)
    def create(self, req, body):
        """Create or import attribute.

        Sending name will generate a key and return private_key
        and fingerprint.

        You can send a public_key to add an existing ssh key

        params: attribute object with:
            name (required) - string
            public_key (optional) - string
        """
	#traceback.print_stack()
        context = req.environ['nova.context']
        authorize(context, action='create')

        try:
            params = body['attribute']
            name = params['name']
        except KeyError:
            msg = _("Invalid request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        
        try:
              attribute=self.api.create_attribute(context, name)

              return {'attribute': attribute}

        except exception.InvalidAttribute as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
   

    def list(self, req):
        """Create or import attribute.

        Sending name will generate a key and return private_key
        and fingerprint.

        You can send a public_key to add an existing ssh key

        params: attribute object with:
            name (required) - string
            public_key (optional) - string
        """
        traceback.print_stack()
        context = req.environ['nova.context']
        #authorize(context, action='create')
        '''
        try:
            params = body['attribute']
            name = params['name']
        except KeyError:
            msg = _("Invalid request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        '''
        try:
	      # for att in attribute:
	      #	print att.name
              attribute=self.api.attribute_list(context)	

        except exception.InvalidAttribute as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
 
    def delete(self, req, id):
        """Delete a attribute with a given name."""
	#print (req,id)
	#traceback.print_stack()
        context = req.environ['nova.context']
        #authorize(context, action='delete')
        try:
	#print("In delete",api)
	     self.api.delete_attribute(context,id)
           # self.api.delete_attribute(context)
        except exception.AttributeNotFound:
            raise webob.exc.HTTPNotFound()
        return webob.Response(status_int=202)

    @wsgi.serializers(xml=AttributeTemplate)
    def show(self, req, id):
        """Return data for the given key name."""
        context = req.environ['nova.context']
        authorize(context, action='show')

        try:
            attribute = self.api.get_key_pair(context, context.user_id, id)
        except exception.AttributeNotFound:
            raise webob.exc.HTTPNotFound()
        return {'attribute': attribute}

    @wsgi.serializers(xml=AttributesTemplate)
    def index(self, req):
        """List of attributes for a user."""
        context = req.environ['nova.context']
        #authorize(context, action='create')
        '''
        try:
            params = body['attribute']
            name = params['name']
        except KeyError:
            msg = _("Invalid request body")
            raise webob.exc.HTTPBadRequest(explanation=msg)
        '''
        try:
	      #print "IASDASDASDASDASDI am here"
              attlist=self.api.list(context)
	      attribute = []
              for att in attlist: 
                attribute.append({'id': att.id,
                           'name': att.name})
	      print attribute 
              return {'attribute': attribute}	
	

        except exception.InvalidAttribute as exc:
            raise webob.exc.HTTPBadRequest(explanation=exc.format_message())
        '''
	context = req.environ['nova.context']
        authorize(context, action='index')
        key_pairs = self.api.get_key_pairs(context, context.user_id)
        rval = []
        for key_pair in key_pairs:
            rval.append({'attribute': self._filter_attribute(key_pair)})

        return {'attributes': rval}
        '''

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


class Attributes(extensions.ExtensionDescriptor):
    """Attribute Support."""
    traceback.print_stack()
    name = "Attributes"
    alias = "os-attributes"
    namespace = "http://docs.openstack.org/compute/ext/attributes/api/v1.1"
    updated = "2011-08-08T00:00:00+00:00"

    def get_resources(self):
        resources = []

        res = extensions.ResourceExtension(
                'os-attributes',
                AttributeController())
        resources.append(res)
        return resources

    def get_controller_extensions(self):
        controller = Controller(self.ext_mgr)
        extension = extensions.ControllerExtension(self, 'servers', controller)
        return [extension]
