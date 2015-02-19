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

import json

from tempest.services.baremetal.v1 import base_v1


class BaremetalClientJSON(base_v1.BaremetalClientV1):
    """Tempest REST client for Ironic JSON API v1."""

    def __init__(self, auth_provider):
        super(BaremetalClientJSON, self).__init__(auth_provider)

        self.serialize = lambda obj_type, obj_body: json.dumps(obj_body)
        self.deserialize = json.loads
