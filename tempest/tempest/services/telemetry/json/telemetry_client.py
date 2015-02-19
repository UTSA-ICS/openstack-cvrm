# Copyright 2014 OpenStack Foundation
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

from tempest.common import rest_client
from tempest.openstack.common import jsonutils as json
import tempest.services.telemetry.telemetry_client_base as client


class TelemetryClientJSON(client.TelemetryClientBase):

    def get_rest_client(self, auth_provider):
        return rest_client.RestClient(auth_provider)

    def deserialize(self, body):
        return json.loads(body.replace("\n", ""))

    def serialize(self, body):
        return json.dumps(body)

    def add_sample(self, sample_list, meter_name, meter_unit, volume,
                   sample_type, resource_id, **kwargs):
        sample = {"counter_name": meter_name, "counter_unit": meter_unit,
                  "counter_volume": volume, "counter_type": sample_type,
                  "resource_id": resource_id}
        for key in kwargs:
            sample[key] = kwargs[key]

        sample_list.append(self.serialize(sample))
        return sample_list

    def create_sample(self, meter_name, sample_list):
        uri = "%s/meters/%s" % (self.uri_prefix, meter_name)
        return self.post(uri, str(sample_list))
