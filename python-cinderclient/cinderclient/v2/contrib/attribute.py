# Copyright (c) 2013 OpenStack Foundation
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

from cinderclient import base
from cinderclient import utils


class Attribute(base.Resource):
    
    def delete(self):
        """
        Delete this flavor.
        """
        self.manager.delete(self)

class AttributeManager(base.Manager):
   
    resource_class = Attribute

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
     
@utils.service_type('volumev2')
def do_list_extensions(client, _args):
    """
    Lists all available os-api extensions.
    """
    extensions = client.list_extensions.show_all()
    fields = ["Name", "Summary", "Alias", "Updated"]
    utils.print_list(extensions, fields)
