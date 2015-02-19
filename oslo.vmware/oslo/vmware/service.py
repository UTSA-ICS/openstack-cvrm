# Copyright (c) 2014 VMware, Inc.
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
Common classes that provide access to vSphere services.
"""

import logging
import os

import netaddr
import requests
import six
import six.moves.http_client as httplib
import suds
from suds import cache
from suds import client
from suds import plugin
from suds import transport

from oslo.utils import timeutils
from oslo.vmware._i18n import _
from oslo.vmware import exceptions
from oslo.vmware import vim_util

CACHE_TIMEOUT = 60 * 60  # One hour cache timeout
ADDRESS_IN_USE_ERROR = 'Address already in use'
CONN_ABORT_ERROR = 'Software caused connection abort'
RESP_NOT_XML_ERROR = 'Response is "text/html", not "text/xml"'

SERVICE_INSTANCE = 'ServiceInstance'

LOG = logging.getLogger(__name__)


class ServiceMessagePlugin(plugin.MessagePlugin):
    """Suds plug-in handling some special cases while calling VI SDK."""

    def add_attribute_for_value(self, node):
        """Helper to handle AnyType.

        Suds does not handle AnyType properly. But VI SDK requires type
        attribute to be set when AnyType is used.

        :param node: XML value node
        """
        if node.name == 'value':
            node.set('xsi:type', 'xsd:string')

    def marshalled(self, context):
        """Modifies the envelope document before it is sent.

        This method provides the plug-in with the opportunity to prune empty
        nodes and fix nodes before sending it to the server.

        :param context: send context
        """
        # Suds builds the entire request object based on the WSDL schema.
        # VI SDK throws server errors if optional SOAP nodes are sent
        # without values; e.g., <test/> as opposed to <test>test</test>.
        context.envelope.prune()
        context.envelope.walk(self.add_attribute_for_value)


class Response(six.BytesIO):
    """Response with an input stream as source."""

    def __init__(self, stream, status=200, headers=None):
        self.status = status
        self.headers = headers or {}
        self.reason = requests.status_codes._codes.get(
            status, [''])[0].upper().replace('_', ' ')
        six.BytesIO.__init__(self, stream)

    @property
    def _original_response(self):
        return self

    @property
    def msg(self):
        return self

    def read(self, chunk_size, **kwargs):
        return six.BytesIO.read(self, chunk_size)

    def info(self):
        return self

    def get_all(self, name, default):
        result = self.headers.get(name)
        if not result:
            return default
        return [result]

    def getheaders(self, name):
        return self.get_all(name, [])

    def release_conn(self):
        self.close()


class LocalFileAdapter(requests.adapters.HTTPAdapter):
    """Transport adapter for local files.

    See http://stackoverflow.com/a/22989322
    """

    def _build_response_from_file(self, request):
        file_path = request.url[7:]
        with open(file_path, 'r') as f:
            buff = bytearray(os.path.getsize(file_path))
            f.readinto(buff)
            resp = Response(buff)
            return self.build_response(request, resp)

    def send(self, request, stream=False, timeout=None,
             verify=True, cert=None, proxies=None):
        return self._build_response_from_file(request)


class RequestsTransport(transport.Transport):
    def __init__(self, cacert=None, insecure=True):
        transport.Transport.__init__(self)
        # insecure flag is used only if cacert is not
        # specified.
        self.verify = cacert if cacert else not insecure
        self.session = requests.Session()
        self.session.mount('file:///', LocalFileAdapter())
        self.cookiejar = self.session.cookies

    def open(self, request):
        resp = self.session.get(request.url, verify=self.verify)
        return six.StringIO(resp.content)

    def send(self, request):
        resp = self.session.post(request.url,
                                 data=request.message,
                                 headers=request.headers,
                                 verify=self.verify)
        return transport.Reply(resp.status_code, resp.headers, resp.content)


class MemoryCache(cache.ObjectCache):
    def __init__(self):
        self._cache = {}

    def get(self, key):
        """Retrieves the value for a key or None."""
        now = timeutils.utcnow_ts()
        for k in list(self._cache):
            (timeout, _value) = self._cache[k]
            if timeout and now >= timeout:
                del self._cache[k]

        return self._cache.get(key, (0, None))[1]

    def put(self, key, value, time=CACHE_TIMEOUT):
        """Sets the value for a key."""
        timeout = 0
        if time != 0:
            timeout = timeutils.utcnow_ts() + time
        self._cache[key] = (timeout, value)
        return True


_CACHE = MemoryCache()


class Service(object):
    """Base class containing common functionality for invoking vSphere
    services
    """

    def __init__(self, wsdl_url=None, soap_url=None,
                 cacert=None, insecure=True):
        self.wsdl_url = wsdl_url
        self.soap_url = soap_url
        LOG.debug("Creating suds client with soap_url='%s' and wsdl_url='%s'",
                  self.soap_url, self.wsdl_url)
        transport = RequestsTransport(cacert, insecure)
        self.client = client.Client(self.wsdl_url,
                                    transport=transport,
                                    location=self.soap_url,
                                    plugins=[ServiceMessagePlugin()],
                                    cache=_CACHE)
        self._service_content = None

    @staticmethod
    def build_base_url(protocol, host, port):
        proto_str = '%s://' % protocol
        host_str = '[%s]' % host if netaddr.valid_ipv6(host) else host
        port_str = '' if port is None else ':%d' % port
        return proto_str + host_str + port_str

    @staticmethod
    def _retrieve_properties_ex_fault_checker(response):
        """Checks the RetrievePropertiesEx API response for errors.

        Certain faults are sent in the SOAP body as a property of missingSet.
        This method raises VimFaultException when a fault is found in the
        response.

        :param response: response from RetrievePropertiesEx API call
        :raises: VimFaultException
        """
        fault_list = []
        details = {}
        if not response:
            # This is the case when the session has timed out. ESX SOAP
            # server sends an empty RetrievePropertiesExResponse. Normally
            # missingSet in the response objects has the specifics about
            # the error, but that's not the case with a timed out idle
            # session. It is as bad as a terminated session for we cannot
            # use the session. Therefore setting fault to NotAuthenticated
            # fault.
            LOG.debug("RetrievePropertiesEx API response is empty; setting "
                      "fault to %s.",
                      exceptions.NOT_AUTHENTICATED)
            fault_list = [exceptions.NOT_AUTHENTICATED]
        else:
            for obj_cont in response.objects:
                if hasattr(obj_cont, 'missingSet'):
                    for missing_elem in obj_cont.missingSet:
                        f_type = missing_elem.fault.fault
                        f_name = f_type.__class__.__name__
                        fault_list.append(f_name)
                        if f_name == exceptions.NO_PERMISSION:
                            details['object'] = f_type.object.value
                            details['privilegeId'] = f_type.privilegeId

        if fault_list:
            fault_string = _("Error occurred while calling "
                             "RetrievePropertiesEx.")
            raise exceptions.VimFaultException(fault_list,
                                               fault_string,
                                               details=details)

    @property
    def service_content(self):
        if self._service_content is None:
            self._service_content = self.retrieve_service_content()
        return self._service_content

    def get_http_cookie(self):
        """Return the vCenter session cookie."""
        cookies = self.client.options.transport.cookiejar
        for cookie in cookies:
            if cookie.name.lower() == 'vmware_soap_session':
                return cookie.value

    def __getattr__(self, attr_name):
        """Returns the method to invoke API identified by param attr_name."""

        def request_handler(managed_object, **kwargs):
            """Handler for vSphere API calls.

            Invokes the API and parses the response for fault checking and
            other errors.

            :param managed_object: managed object reference argument of the
                                   API call
            :param kwargs: keyword arguments of the API call
            :returns: response of the API call
            :raises: VimException, VimFaultException, VimAttributeException,
                     VimSessionOverLoadException, VimConnectionException
            """
            try:
                if isinstance(managed_object, str):
                    # For strings, use string value for value and type
                    # of the managed object.
                    managed_object = vim_util.get_moref(managed_object,
                                                        managed_object)
                if managed_object is None:
                    return
                request = getattr(self.client.service, attr_name)
                response = request(managed_object, **kwargs)
                if (attr_name.lower() == 'retrievepropertiesex'):
                    Service._retrieve_properties_ex_fault_checker(response)
                return response
            except exceptions.VimFaultException:
                # Catch the VimFaultException that is raised by the fault
                # check of the SOAP response.
                raise

            except suds.WebFault as excep:
                fault_string = None
                if excep.fault:
                    fault_string = excep.fault.faultstring

                doc = excep.document
                detail = None
                if doc is not None:
                    detail = doc.childAtPath('/detail')
                    if not detail:
                        # NOTE(arnaud): this is needed with VC 5.1
                        detail = doc.childAtPath('/Envelope/Body/Fault/detail')
                fault_list = []
                details = {}
                if detail:
                    for fault in detail.getChildren():
                        fault_list.append(fault.get("type"))
                        for child in fault.getChildren():
                            details[child.name] = child.getText()
                raise exceptions.VimFaultException(fault_list, fault_string,
                                                   excep, details)

            except AttributeError as excep:
                raise exceptions.VimAttributeException(
                    _("No such SOAP method %s.") % attr_name, excep)

            except (httplib.CannotSendRequest,
                    httplib.ResponseNotReady,
                    httplib.CannotSendHeader) as excep:
                raise exceptions.VimSessionOverLoadException(
                    _("httplib error in %s.") % attr_name, excep)

            except requests.RequestException as excep:
                raise exceptions.VimConnectionException(
                    _("requests error in %s.") % attr_name, excep)

            except Exception as excep:
                # TODO(vbala) should catch specific exceptions and raise
                # appropriate VimExceptions.

                # Socket errors which need special handling; some of these
                # might be caused by server API call overload.
                if (six.text_type(excep).find(ADDRESS_IN_USE_ERROR) != -1 or
                        six.text_type(excep).find(CONN_ABORT_ERROR)) != -1:
                    raise exceptions.VimSessionOverLoadException(
                        _("Socket error in %s.") % attr_name, excep)
                # Type error which needs special handling; it might be caused
                # by server API call overload.
                elif six.text_type(excep).find(RESP_NOT_XML_ERROR) != -1:
                    raise exceptions.VimSessionOverLoadException(
                        _("Type error in %s.") % attr_name, excep)
                else:
                    raise exceptions.VimException(
                        _("Exception in %s.") % attr_name, excep)
        return request_handler

    def __repr__(self):
        return "vSphere object"

    def __str__(self):
        return "vSphere object"
