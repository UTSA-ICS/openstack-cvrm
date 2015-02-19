# Copyright 2012 OpenStack Foundation.
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

import jsonschema
import six

from glance.common import exception


class Schema(object):

    def __init__(self, name, properties=None, links=None):
        self.name = name
        if properties is None:
            properties = {}
        self.properties = properties
        self.links = links

    def validate(self, obj):
        try:
            jsonschema.validate(obj, self.raw())
        except jsonschema.ValidationError as e:
            raise exception.InvalidObject(schema=self.name,
                                          reason=six.text_type(e))

    def filter(self, obj):
        filtered = {}
        for key, value in obj.iteritems():
            if self._filter_func(self.properties, key) and value is not None:
                filtered[key] = value
        return filtered

    @staticmethod
    def _filter_func(properties, key):
        return key in properties

    def merge_properties(self, properties):
        # Ensure custom props aren't attempting to override base props
        original_keys = set(self.properties.keys())
        new_keys = set(properties.keys())
        intersecting_keys = original_keys.intersection(new_keys)
        conflicting_keys = [k for k in intersecting_keys
                            if self.properties[k] != properties[k]]
        if conflicting_keys:
            props = ', '.join(conflicting_keys)
            reason = _("custom properties (%(props)s) conflict "
                       "with base properties")
            raise exception.SchemaLoadError(reason=reason % {'props': props})

        self.properties.update(properties)

    def raw(self):
        raw = {
            'name': self.name,
            'properties': self.properties,
            'additionalProperties': False,
        }
        if self.links:
            raw['links'] = self.links
        return raw

    def minimal(self):
        minimal = {
            'name': self.name,
            'properties': self.properties
        }
        return minimal


class PermissiveSchema(Schema):
    @staticmethod
    def _filter_func(properties, key):
        return True

    def raw(self):
        raw = super(PermissiveSchema, self).raw()
        raw['additionalProperties'] = {'type': 'string'}
        return raw

    def minimal(self):
        minimal = super(PermissiveSchema, self).raw()
        return minimal


class CollectionSchema(object):

    def __init__(self, name, item_schema):
        self.name = name
        self.item_schema = item_schema

    def raw(self):
        return {
            'name': self.name,
            'properties': {
                self.name: {
                    'type': 'array',
                    'items': self.item_schema.raw(),
                },
                'first': {'type': 'string'},
                'next': {'type': 'string'},
                'schema': {'type': 'string'},
            },
            'links': [
                {'rel': 'first', 'href': '{first}'},
                {'rel': 'next', 'href': '{next}'},
                {'rel': 'describedby', 'href': '{schema}'},
            ],
        }

    def minimal(self):
        return {
            'name': self.name,
            'properties': {
                self.name: {
                    'type': 'array',
                    'items': self.item_schema.minimal(),
                },
                'schema': {'type': 'string'},
            },
            'links': [
                {'rel': 'describedby', 'href': '{schema}'},
            ],
        }
