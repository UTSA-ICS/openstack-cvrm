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

"""
Utility methods for working with WSGI servers redux
"""

import sys

import netaddr
import six
import webob.dec
import webob.exc

from neutron.api.v2 import attributes
from neutron.common import exceptions
from neutron.openstack.common import gettextutils
from neutron.openstack.common import log as logging
from neutron import wsgi


LOG = logging.getLogger(__name__)


class Request(wsgi.Request):
    pass


def Resource(controller, faults=None, deserializers=None, serializers=None):
    """Represents an API entity resource and the associated serialization and
    deserialization logic
    """
    xml_deserializer = wsgi.XMLDeserializer(attributes.get_attr_metadata())
    default_deserializers = {'application/xml': xml_deserializer,
                             'application/json': wsgi.JSONDeserializer()}
    xml_serializer = wsgi.XMLDictSerializer(attributes.get_attr_metadata())
    default_serializers = {'application/xml': xml_serializer,
                           'application/json': wsgi.JSONDictSerializer()}
    format_types = {'xml': 'application/xml',
                    'json': 'application/json'}
    action_status = dict(create=201, delete=204)

    default_deserializers.update(deserializers or {})
    default_serializers.update(serializers or {})

    deserializers = default_deserializers
    serializers = default_serializers
    faults = faults or {}

    @webob.dec.wsgify(RequestClass=Request)
    def resource(request):
        route_args = request.environ.get('wsgiorg.routing_args')
        if route_args:
            args = route_args[1].copy()
        else:
            args = {}

        # NOTE(jkoelker) by now the controller is already found, remove
        #                it from the args if it is in the matchdict
        args.pop('controller', None)
        fmt = args.pop('format', None)
        action = args.pop('action', None)
        content_type = format_types.get(fmt,
                                        request.best_match_content_type())
        language = request.best_match_language()
        deserializer = deserializers.get(content_type)
        serializer = serializers.get(content_type)

        try:
            if request.body:
                args['body'] = deserializer.deserialize(request.body)['body']

            method = getattr(controller, action)

            result = method(request=request, **args)
        except (exceptions.NeutronException,
                netaddr.AddrFormatError) as e:
            for fault in faults:
                if isinstance(e, fault):
                    mapped_exc = faults[fault]
                    break
            else:
                mapped_exc = webob.exc.HTTPInternalServerError
            if 400 <= mapped_exc.code < 500:
                LOG.info(_('%(action)s failed (client error): %(exc)s'),
                         {'action': action, 'exc': e})
            else:
                LOG.exception(_('%s failed'), action)
            e = translate(e, language)
            # following structure is expected by python-neutronclient
            err_data = {'type': e.__class__.__name__,
                        'message': e, 'detail': ''}
            body = serializer.serialize({'NeutronError': err_data})
            kwargs = {'body': body, 'content_type': content_type}
            raise mapped_exc(**kwargs)
        except webob.exc.HTTPException as e:
            type_, value, tb = sys.exc_info()
            LOG.exception(_('%s failed'), action)
            translate(e, language)
            value.body = serializer.serialize({'NeutronError': e})
            value.content_type = content_type
            six.reraise(type_, value, tb)
        except NotImplementedError as e:
            e = translate(e, language)
            # NOTE(armando-migliaccio): from a client standpoint
            # it makes sense to receive these errors, because
            # extensions may or may not be implemented by
            # the underlying plugin. So if something goes south,
            # because a plugin does not implement a feature,
            # returning 500 is definitely confusing.
            body = serializer.serialize(
                {'NotImplementedError': e.message})
            kwargs = {'body': body, 'content_type': content_type}
            raise webob.exc.HTTPNotImplemented(**kwargs)
        except Exception:
            # NOTE(jkoelker) Everything else is 500
            LOG.exception(_('%s failed'), action)
            # Do not expose details of 500 error to clients.
            msg = _('Request Failed: internal server error while '
                    'processing your request.')
            msg = translate(msg, language)
            body = serializer.serialize({'NeutronError': msg})
            kwargs = {'body': body, 'content_type': content_type}
            raise webob.exc.HTTPInternalServerError(**kwargs)

        status = action_status.get(action, 200)
        body = serializer.serialize(result)
        # NOTE(jkoelker) Comply with RFC2616 section 9.7
        if status == 204:
            content_type = ''
            body = None

        return webob.Response(request=request, status=status,
                              content_type=content_type,
                              body=body)
    return resource


def translate(translatable, locale):
    """Translates the object to the given locale.

    If the object is an exception its translatable elements are translated
    in place, if the object is a translatable string it is translated and
    returned. Otherwise, the object is returned as-is.

    :param translatable: the object to be translated
    :param locale: the locale to translate to
    :returns: the translated object, or the object as-is if it
              was not translated
    """
    localize = gettextutils.translate
    if isinstance(translatable, exceptions.NeutronException):
        translatable.msg = localize(translatable.msg, locale)
    elif isinstance(translatable, webob.exc.HTTPError):
        translatable.detail = localize(translatable.detail, locale)
    elif isinstance(translatable, Exception):
        translatable.message = localize(translatable.message, locale)
    else:
        return localize(translatable, locale)
    return translatable
