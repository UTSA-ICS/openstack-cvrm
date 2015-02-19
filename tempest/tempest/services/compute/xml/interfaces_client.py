# Copyright 2013 IBM Corp.
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

import time

from lxml import etree

from tempest.common import rest_client
from tempest.common import xml_utils
from tempest import config
from tempest import exceptions

CONF = config.CONF


class InterfacesClientXML(rest_client.RestClient):
    TYPE = "xml"

    def __init__(self, auth_provider):
        super(InterfacesClientXML, self).__init__(auth_provider)
        self.service = CONF.compute.catalog_type

    def _process_xml_interface(self, node):
        iface = xml_utils.xml_to_json(node)
        # NOTE(danms): if multiple addresses per interface is ever required,
        # xml_utils.xml_to_json will need to be fixed or replaced in this case
        iface['fixed_ips'] = [dict(iface['fixed_ips']['fixed_ip'].items())]
        return iface

    def list_interfaces(self, server):
        resp, body = self.get('servers/%s/os-interface' % server)
        node = etree.fromstring(body)
        interfaces = [self._process_xml_interface(x)
                      for x in node.getchildren()]
        return resp, interfaces

    def create_interface(self, server, port_id=None, network_id=None,
                         fixed_ip=None):
        doc = xml_utils.Document()
        iface = xml_utils.Element('interfaceAttachment')
        if port_id:
            _port_id = xml_utils.Element('port_id')
            _port_id.append(xml_utils.Text(port_id))
            iface.append(_port_id)
        if network_id:
            _network_id = xml_utils.Element('net_id')
            _network_id.append(xml_utils.Text(network_id))
            iface.append(_network_id)
        if fixed_ip:
            _fixed_ips = xml_utils.Element('fixed_ips')
            _fixed_ip = xml_utils.Element('fixed_ip')
            _ip_address = xml_utils.Element('ip_address')
            _ip_address.append(xml_utils.Text(fixed_ip))
            _fixed_ip.append(_ip_address)
            _fixed_ips.append(_fixed_ip)
            iface.append(_fixed_ips)
        doc.append(iface)
        resp, body = self.post('servers/%s/os-interface' % server,
                               body=str(doc))
        body = self._process_xml_interface(etree.fromstring(body))
        return resp, body

    def show_interface(self, server, port_id):
        resp, body = self.get('servers/%s/os-interface/%s' % (server, port_id))
        body = self._process_xml_interface(etree.fromstring(body))
        return resp, body

    def delete_interface(self, server, port_id):
        resp, body = self.delete('servers/%s/os-interface/%s' % (server,
                                                                 port_id))
        return resp, body

    def wait_for_interface_status(self, server, port_id, status):
        """Waits for a interface to reach a given status."""
        resp, body = self.show_interface(server, port_id)
        interface_status = body['port_state']
        start = int(time.time())

        while(interface_status != status):
            time.sleep(self.build_interval)
            resp, body = self.show_interface(server, port_id)
            interface_status = body['port_state']

            timed_out = int(time.time()) - start >= self.build_timeout

            if interface_status != status and timed_out:
                message = ('Interface %s failed to reach %s status within '
                           'the required time (%s s).' %
                           (port_id, status, self.build_timeout))
                raise exceptions.TimeoutException(message)
        return resp, body

    def add_fixed_ip(self, server_id, network_id):
        """Add a fixed IP to input server instance."""
        post_body = xml_utils.Element("addFixedIp",
                                      xmlns=xml_utils.XMLNS_11,
                                      networkId=network_id)
        resp, body = self.post('servers/%s/action' % str(server_id),
                               str(xml_utils.Document(post_body)))
        return resp, body

    def remove_fixed_ip(self, server_id, ip_address):
        """Remove input fixed IP from input server instance."""
        post_body = xml_utils.Element("removeFixedIp",
                                      xmlns=xml_utils.XMLNS_11,
                                      address=ip_address)
        resp, body = self.post('servers/%s/action' % str(server_id),
                               str(xml_utils.Document(post_body)))
        return resp, body
