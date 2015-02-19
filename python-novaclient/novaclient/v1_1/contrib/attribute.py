# Copyright 2010 Jacob Kaplan-Moss
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
Attribute interface.
"""

from oslo.utils import strutils
from six.moves.urllib import parse

from novaclient import base
from novaclient import exceptions
from novaclient.i18n import _
from novaclient import utils


class Attribute(base.Resource):
    """
    A flavor is an available hardware configuration for a server.
    """
    HUMAN_ID = True


    def delete(self):
        """
        Delete this flavor.
        """
        self.manager.delete(self)


class AttributeManager(base.ManagerWithFind):
    """
    Manage :class:`Flavor` resources.
    """
    resource_class = Attribute
    #is_alphanum_id_allowed = True
    '''
    def list(self, detailed=True, is_public=True):
        """
        Get a list of all flavors.

        :rtype: list of :class:`Flavor`.
        """
	print("in FlavorManager")
        qparams = {}
        # is_public is ternary - None means give all flavors.
        # By default Nova assumes True and gives admins public flavors
        # and flavors from their own projects only.
        if not is_public:
            qparams['is_public'] = is_public
        query_string = "?%s" % parse.urlencode(qparams) if qparams else ""

        detail = ""
        if detailed:
            detail = "/detail"

        return self._list("/flavors%s%s" % (detail, query_string), "flavors")
    '''
    def get(self, flavor):
        """
        Get a specific flavor.

        :param flavor: The ID of the :class:`Flavor` to get.
        :rtype: :class:`Flavor`
        """
        return self._get("/flavors/%s" % base.getid(flavor), "flavor")

    def delete(self, attribute):
        """
        Delete a specific flavor.

        :param flavor: The ID of the :class:`Flavor` to get.
        """
        self._delete("/os-attributes/%s" % base.getid(attribute))

    def _build_body(self, name):
	return{
            "attribute": {
                "name": name.name
            }
        }

    def create(self, name):
	print ("in Create")
	#print "This is naem", name
        body = self._build_body(name)
	#print "This is body",body
        return self._create("/os-attributes", body, "attribute")
    
    def value_set(self, args):
	print ("in value)set")
	#print "This is naem", name
        body = {"attribute_value":{"value":args.value}}
	print "This is body",body["attribute_value"]["value"]
        url="/os-attributes/%s" % args.id
        return self._update(url, body, "attribute")

    def list(self):
        """
        Get a list of all attributes

        """
	#print "inList"
        return self._list("/os-attributes", "attribute")
