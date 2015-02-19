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

import testtools

from neutron.api.v2 import attributes
from neutron.tests import base
from neutron import wsgi


class ExpectedException(testtools.ExpectedException):
    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        if super(ExpectedException, self).__exit__(exc_type,
                                                   exc_value,
                                                   traceback):
            self.exception = exc_value
            return True
        return False


def create_request(path, body, content_type, method='GET',
                   query_string=None, context=None):
    if query_string:
        url = "%s?%s" % (path, query_string)
    else:
        url = path
    req = wsgi.Request.blank(url)
    req.method = method
    req.headers = {}
    req.headers['Accept'] = content_type
    req.body = body
    if context:
        req.environ['neutron.context'] = context
    return req


class WebTestCase(base.BaseTestCase):
    fmt = 'json'

    def setUp(self):
        super(WebTestCase, self).setUp()
        json_deserializer = wsgi.JSONDeserializer()
        xml_deserializer = wsgi.XMLDeserializer(
            attributes.get_attr_metadata())
        self._deserializers = {
            'application/json': json_deserializer,
            'application/xml': xml_deserializer,
        }

    def deserialize(self, response):
        ctype = 'application/%s' % self.fmt
        data = self._deserializers[ctype].deserialize(response.body)['body']
        return data

    def serialize(self, data):
        ctype = 'application/%s' % self.fmt
        result = wsgi.Serializer(
            attributes.get_attr_metadata()).serialize(data, ctype)
        return result


class SubDictMatch(object):

    def __init__(self, sub_dict):
        self.sub_dict = sub_dict

    def __eq__(self, super_dict):
        return all(item in super_dict.items()
                   for item in self.sub_dict.items())
