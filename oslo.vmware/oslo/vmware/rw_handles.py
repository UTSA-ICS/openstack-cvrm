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
Classes defining read and write handles for image transfer.

This module defines various classes for reading and writing files including
VMDK files in VMware servers. It also contains a class to read images from
glance server.
"""

import logging
import socket

import netaddr
import six.moves.http_client as httplib
import six.moves.urllib.parse as urlparse
import six.moves.urllib.request as urllib2

from oslo.utils import excutils
from oslo.vmware._i18n import _, _LE, _LW
from oslo.vmware import exceptions
from oslo.vmware import vim_util


LOG = logging.getLogger(__name__)

MIN_PROGRESS_DIFF_TO_LOG = 25
READ_CHUNKSIZE = 65536
USER_AGENT = 'OpenStack-ESX-Adapter'


class FileHandle(object):
    """Base class for VMware server file (including VMDK) access over HTTP.

    This class wraps a backing file handle and provides utility methods
    for various sub-classes.
    """

    def __init__(self, file_handle):
        """Initializes the file handle.

        :param file_handle: backing file handle
        """
        self._eof = False
        self._file_handle = file_handle
        self._last_logged_progress = 0

    def close(self):
        """Close the file handle."""
        try:
            self._file_handle.close()
        except Exception:
            LOG.warn(_LW("Error occurred while closing the file handle"),
                     exc_info=True)

    def _build_vim_cookie_header(self, vim_cookies):
        """Build ESX host session cookie header."""
        cookie_header = ""
        for vim_cookie in vim_cookies:
            cookie_header = vim_cookie.name + '=' + vim_cookie.value
            break
        return cookie_header

    def write(self, data):
        """Write data to the file.

        :param data: data to be written
        :raises: NotImplementedError
        """
        raise NotImplementedError()

    def read(self, chunk_size):
        """Read a chunk of data.

        :param chunk_size: read chunk size
        :raises: NotImplementedError
        """
        raise NotImplementedError()

    def get_size(self):
        """Get size of the file to be read.

        :raises: NotImplementedError
        """
        raise NotImplementedError()

    def _is_valid_ipv6(self, address):
        """Checks whether the given host address is a valid IPv6 address."""
        try:
            return netaddr.valid_ipv6(address)
        except Exception:
            return False

    def _get_soap_url(self, scheme, host, port):
        """Returns the IPv4/v6 compatible SOAP URL for the given host."""
        if self._is_valid_ipv6(host):
            return '%s://[%s]:%d' % (scheme, host, port)
        return '%s://%s:%d' % (scheme, host, port)

    def _fix_esx_url(self, url, host, port):
        """Fix netloc in the case of an ESX host.

        In the case of an ESX host, the netloc is set to '*' in the URL
        returned in HttpNfcLeaseInfo. It should be replaced with host name
        or IP address.
        """
        urlp = urlparse.urlparse(url)
        if urlp.netloc == '*':
            scheme, netloc, path, params, query, fragment = urlp
            if netaddr.valid_ipv6(host):
                netloc = '[%s]:%d' % (host, port)
            else:
                netloc = "%s:%d" % (host, port)
            url = urlparse.urlunparse((scheme,
                                       netloc,
                                       path,
                                       params,
                                       query,
                                       fragment))
        return url

    def _find_vmdk_url(self, lease_info, host, port):
        """Find the URL corresponding to a VMDK file in lease info."""
        url = None
        for deviceUrl in lease_info.deviceUrl:
            if deviceUrl.disk:
                url = self._fix_esx_url(deviceUrl.url, host, port)
                break
        if not url:
            excep_msg = _("Could not retrieve VMDK URL from lease info.")
            LOG.error(excep_msg)
            raise exceptions.VimException(excep_msg)
        LOG.debug("Found VMDK URL: %s from lease info.", url)
        return url

    def _log_progress(self, progress):
        """Log data transfer progress."""
        if (progress == 100 or (progress - self._last_logged_progress >=
                                MIN_PROGRESS_DIFF_TO_LOG)):
            LOG.debug("Data transfer progress is %d%%.", progress)
            self._last_logged_progress = progress


class FileWriteHandle(FileHandle):
    """Write handle for a file in VMware server."""

    def __init__(self, host, port, data_center_name, datastore_name, cookies,
                 file_path, file_size, scheme='https'):
        """Initializes the write handle with given parameters.

        :param host: ESX/VC server IP address or host name
        :param port: port for connection
        :param data_center_name: name of the data center in the case of a VC
                                 server
        :param datastore_name: name of the datastore where the file is stored
        :param cookies: cookies to build the vim cookie header
        :param file_path: datastore path where the file is written
        :param file_size: size of the file in bytes
        :param scheme: protocol-- http or https
        :raises: VimConnectionException, ValueError
        """
        soap_url = self._get_soap_url(scheme, host, port)
        param_list = {'dcPath': data_center_name, 'dsName': datastore_name}
        self._url = '%s/folder/%s' % (soap_url, file_path)
        self._url = self._url + '?' + urlparse.urlencode(param_list)

        self.conn = self._create_connection(self._url,
                                            file_size,
                                            cookies)
        FileHandle.__init__(self, self.conn)

    def _create_connection(self, url, file_size, cookies):
        """Create HTTP connection to write to the file with given URL."""
        LOG.debug("Creating HTTP connection to write to file with "
                  "size = %(file_size)d and URL = %(url)s.",
                  {'file_size': file_size,
                   'url': url})
        _urlparse = urlparse.urlparse(url)
        scheme, netloc, path, params, query, fragment = _urlparse

        try:
            if scheme == 'http':
                conn = httplib.HTTPConnection(netloc)
            elif scheme == 'https':
                conn = httplib.HTTPSConnection(netloc)
            else:
                excep_msg = _("Invalid scheme: %s.") % scheme
                LOG.error(excep_msg)
                raise ValueError(excep_msg)

            conn.putrequest('PUT', path + '?' + query)
            conn.putheader('User-Agent', USER_AGENT)
            conn.putheader('Content-Length', file_size)
            conn.putheader('Cookie', self._build_vim_cookie_header(cookies))
            conn.endheaders()
            return conn
        except (httplib.InvalidURL, httplib.CannotSendRequest,
                httplib.CannotSendHeader) as excep:
            excep_msg = _("Error occurred while creating HTTP connection "
                          "to write to file with URL = %s.") % url
            LOG.exception(excep_msg)
            raise exceptions.VimConnectionException(excep_msg, excep)

    def write(self, data):
        """Write data to the file.

        :param data: data to be written
        :raises: VimConnectionException, VimException
        """
        try:
            self._file_handle.send(data)
        except (socket.error, httplib.NotConnected) as excep:
            excep_msg = _("Connection error occurred while writing data to"
                          " %s.") % self._url
            LOG.exception(excep_msg)
            raise exceptions.VimConnectionException(excep_msg, excep)
        except Exception as excep:
            # TODO(vbala) We need to catch and raise specific exceptions
            # related to connection problems, invalid request and invalid
            # arguments.
            excep_msg = _("Error occurred while writing data to"
                          " %s.") % self._url
            LOG.exception(excep_msg)
            raise exceptions.VimException(excep_msg, excep)

    def close(self):
        """Get the response and close the connection."""
        LOG.debug("Closing write handle for %s.", self._url)
        try:
            self.conn.getresponse()
        except Exception:
            LOG.warn(_LW("Error occurred while reading the HTTP response."),
                     exc_info=True)
        super(FileWriteHandle, self).close()

    def __str__(self):
        return "File write handle for %s" % self._url


class VmdkWriteHandle(FileHandle):
    """VMDK write handle based on HttpNfcLease.

    This class creates a vApp in the specified resource pool and uploads the
    virtual disk contents.
    """

    def __init__(self, session, host, port, rp_ref, vm_folder_ref, import_spec,
                 vmdk_size):
        """Initializes the VMDK write handle with input parameters.

        :param session: valid API session to ESX/VC server
        :param host: ESX/VC server IP address or host name
        :param port: port for connection
        :param rp_ref: resource pool into which the backing VM is imported
        :param vm_folder_ref: VM folder in ESX/VC inventory to use as parent
                              of backing VM
        :param import_spec: import specification of the backing VM
        :param vmdk_size: size of the backing VM's VMDK file
        :raises: VimException, VimFaultException, VimAttributeException,
                 VimSessionOverLoadException, VimConnectionException,
                 ValueError
        """
        self._session = session
        self._vmdk_size = vmdk_size
        self._bytes_written = 0

        # Get lease and its info for vApp import
        self._lease = self._create_and_wait_for_lease(session,
                                                      rp_ref,
                                                      import_spec,
                                                      vm_folder_ref)
        LOG.debug("Invoking VIM API for reading info of lease: %s.",
                  self._lease)
        lease_info = session.invoke_api(vim_util,
                                        'get_object_property',
                                        session.vim,
                                        self._lease,
                                        'info')

        # Find VMDK URL where data is to be written
        self._url = self._find_vmdk_url(lease_info, host, port)
        self._vm_ref = lease_info.entity

        # Create HTTP connection to write to VMDK URL
        self._conn = self._create_connection(session, self._url, vmdk_size)
        FileHandle.__init__(self, self._conn)

    def get_imported_vm(self):
        """"Get managed object reference of the VM created for import."""
        return self._vm_ref

    def _create_and_wait_for_lease(self, session, rp_ref, import_spec,
                                   vm_folder_ref):
        """Create and wait for HttpNfcLease lease for vApp import."""
        LOG.debug("Creating HttpNfcLease lease for vApp import into resource"
                  " pool: %s.",
                  rp_ref)
        lease = session.invoke_api(session.vim,
                                   'ImportVApp',
                                   rp_ref,
                                   spec=import_spec,
                                   folder=vm_folder_ref)
        LOG.debug("Lease: %(lease)s obtained for vApp import into resource"
                  " pool %(rp_ref)s.",
                  {'lease': lease,
                   'rp_ref': rp_ref})
        session.wait_for_lease_ready(lease)
        return lease

    def _create_connection(self, session, url, vmdk_size):
        """Create HTTP connection to write to VMDK file."""
        LOG.debug("Creating HTTP connection to write to VMDK file with "
                  "size = %(vmdk_size)d and URL = %(url)s.",
                  {'vmdk_size': vmdk_size,
                   'url': url})
        cookies = session.vim.client.options.transport.cookiejar
        _urlparse = urlparse.urlparse(url)
        scheme, netloc, path, params, query, fragment = _urlparse

        try:
            if scheme == 'http':
                conn = httplib.HTTPConnection(netloc)
            elif scheme == 'https':
                conn = httplib.HTTPSConnection(netloc)
            else:
                excep_msg = _("Invalid scheme: %s.") % scheme
                LOG.error(excep_msg)
                raise ValueError(excep_msg)

            if query:
                path = path + '?' + query
            conn.putrequest('PUT', path)
            conn.putheader('User-Agent', USER_AGENT)
            conn.putheader('Content-Length', str(vmdk_size))
            conn.putheader('Overwrite', 't')
            conn.putheader('Cookie', self._build_vim_cookie_header(cookies))
            conn.putheader('Content-Type', 'binary/octet-stream')
            conn.endheaders()
            return conn
        except (httplib.InvalidURL, httplib.CannotSendRequest,
                httplib.CannotSendHeader) as excep:
            excep_msg = _("Error occurred while creating HTTP connection "
                          "to write to VMDK file with URL = %s.") % url
            LOG.exception(excep_msg)
            raise exceptions.VimConnectionException(excep_msg, excep)

    def write(self, data):
        """Write data to the file.

        :param data: data to be written
        :raises: VimConnectionException, VimException
        """
        try:
            self._file_handle.send(data)
            self._bytes_written += len(data)
        except (socket.error, httplib.NotConnected) as excep:
            excep_msg = _("Connection error occurred while writing data to"
                          " %s.") % self._url
            LOG.exception(excep_msg)
            raise exceptions.VimConnectionException(excep_msg, excep)
        except Exception as excep:
            # TODO(vbala) We need to catch and raise specific exceptions
            # related to connection problems, invalid request and invalid
            # arguments.
            excep_msg = _("Error occurred while writing data to"
                          " %s.") % self._url
            LOG.exception(excep_msg)
            raise exceptions.VimException(excep_msg, excep)

    # TODO(vbala) Move this method to FileHandle.
    def update_progress(self):
        """Updates progress to lease.

        This call back to the lease is essential to keep the lease alive
        across long running write operations.

        :raises: VimException, VimFaultException, VimAttributeException,
                 VimSessionOverLoadException, VimConnectionException
        """
        progress = int(float(self._bytes_written) / self._vmdk_size * 100)
        self._log_progress(progress)

        try:
            self._session.invoke_api(self._session.vim,
                                     'HttpNfcLeaseProgress',
                                     self._lease,
                                     percent=progress)
        except exceptions.VimException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error occurred while updating the "
                                  "write progress of VMDK file with "
                                  "URL = %s."),
                              self._url)

    def close(self):
        """Releases the lease and close the connection.

        :raises: VimException, VimFaultException, VimAttributeException,
                 VimSessionOverLoadException, VimConnectionException
        """
        LOG.debug("Getting lease state for %s.", self._url)
        try:
            state = self._session.invoke_api(vim_util,
                                             'get_object_property',
                                             self._session.vim,
                                             self._lease,
                                             'state')
            LOG.debug("Lease for %(url)s is in state: %(state)s.",
                      {'url': self._url,
                       'state': state})
            if state == 'ready':
                LOG.debug("Releasing lease for %s.", self._url)
                self._session.invoke_api(self._session.vim,
                                         'HttpNfcLeaseComplete',
                                         self._lease)
            else:
                LOG.debug("Lease for %(url)s is in state: %(state)s; no "
                          "need to release.",
                          {'url': self._url,
                           'state': state})
        except exceptions.VimException:
            LOG.warn(_LW("Error occurred while releasing the lease for %s."),
                     self._url,
                     exc_info=True)
        super(VmdkWriteHandle, self).close()
        LOG.debug("Closed VMDK write handle for %s.", self._url)

    def __str__(self):
        return "VMDK write handle for %s" % self._url


class VmdkReadHandle(FileHandle):
    """VMDK read handle based on HttpNfcLease."""

    def __init__(self, session, host, port, vm_ref, vmdk_path, vmdk_size):
        """Initializes the VMDK read handle with the given parameters.

        During the read (export) operation, the VMDK file is converted to a
        stream-optimized sparse disk format. Therefore, the size of the VMDK
        file read may be smaller than the actual VMDK size.

        :param session: valid api session to ESX/VC server
        :param host: ESX/VC server IP address or host name
        :param port: port for connection
        :param vm_ref: managed object reference of the backing VM whose VMDK
                       is to be exported
        :param vmdk_path: path of the VMDK file to be exported
        :param vmdk_size: actual size of the VMDK file
        :raises: VimException, VimFaultException, VimAttributeException,
                 VimSessionOverLoadException, VimConnectionException
        """
        self._session = session
        self._vmdk_size = vmdk_size
        self._bytes_read = 0

        # Obtain lease for VM export
        self._lease = self._create_and_wait_for_lease(session, vm_ref)
        LOG.debug("Invoking VIM API for reading info of lease: %s.",
                  self._lease)
        lease_info = session.invoke_api(vim_util,
                                        'get_object_property',
                                        session.vim,
                                        self._lease,
                                        'info')

        # find URL of the VMDK file to be read and open connection
        self._url = self._find_vmdk_url(lease_info, host, port)
        self._conn = self._create_connection(session, self._url)
        FileHandle.__init__(self, self._conn)

    def _create_and_wait_for_lease(self, session, vm_ref):
        """Create and wait for HttpNfcLease lease for VM export."""
        LOG.debug("Creating HttpNfcLease lease for exporting VM: %s.",
                  vm_ref)
        lease = session.invoke_api(session.vim, 'ExportVm', vm_ref)
        LOG.debug("Lease: %(lease)s obtained for exporting VM: %(vm_ref)s.",
                  {'lease': lease,
                   'vm_ref': vm_ref})
        session.wait_for_lease_ready(lease)
        return lease

    def _create_connection(self, session, url):
        LOG.debug("Opening URL: %s for reading.", url)
        try:
            cookies = session.vim.client.options.transport.cookiejar
            headers = {'User-Agent': USER_AGENT,
                       'Cookie': self._build_vim_cookie_header(cookies)}
            request = urllib2.Request(url, None, headers)
            conn = urllib2.urlopen(request)
            return conn
        except Exception as excep:
            # TODO(vbala) We need to catch and raise specific exceptions
            # related to connection problems, invalid request and invalid
            # arguments.
            excep_msg = _("Error occurred while opening URL: %s for "
                          "reading.") % url
            LOG.exception(excep_msg)
            raise exceptions.VimException(excep_msg, excep)

    def read(self, chunk_size):
        """Read a chunk of data from the VMDK file.

        :param chunk_size: size of read chunk
        :returns: the data
        :raises: VimException
        """
        try:
            data = self._file_handle.read(READ_CHUNKSIZE)
            self._bytes_read += len(data)
            return data
        except Exception as excep:
            # TODO(vbala) We need to catch and raise specific exceptions
            # related to connection problems, invalid request and invalid
            # arguments.
            excep_msg = _("Error occurred while reading data from"
                          " %s.") % self._url
            LOG.exception(excep_msg)
            raise exceptions.VimException(excep_msg, excep)

    def update_progress(self):
        """Updates progress to lease.

        This call back to the lease is essential to keep the lease alive
        across long running read operations.

        :raises: VimException, VimFaultException, VimAttributeException,
                 VimSessionOverLoadException, VimConnectionException
        """
        progress = int(float(self._bytes_read) / self._vmdk_size * 100)
        self._log_progress(progress)

        try:
            self._session.invoke_api(self._session.vim,
                                     'HttpNfcLeaseProgress',
                                     self._lease,
                                     percent=progress)
        except exceptions.VimException:
            with excutils.save_and_reraise_exception():
                LOG.exception(_LE("Error occurred while updating the "
                                  "read progress of VMDK file with URL = %s."),
                              self._url)

    def close(self):
        """Releases the lease and close the connection.

        :raises: VimException, VimFaultException, VimAttributeException,
                 VimSessionOverLoadException, VimConnectionException
        """
        LOG.debug("Getting lease state for %s.", self._url)
        try:
            state = self._session.invoke_api(vim_util,
                                             'get_object_property',
                                             self._session.vim,
                                             self._lease,
                                             'state')
            LOG.debug("Lease for %(url)s is in state: %(state)s.",
                      {'url': self._url,
                       'state': state})
            if state == 'ready':
                LOG.debug("Releasing lease for %s.", self._url)
                self._session.invoke_api(self._session.vim,
                                         'HttpNfcLeaseComplete',
                                         self._lease)
            else:
                LOG.debug("Lease for %(url)s is in state: %(state)s; no "
                          "need to release.",
                          {'url': self._url,
                           'state': state})
        except exceptions.VimException:
            LOG.warn(_LW("Error occurred while releasing the lease for %s."),
                     self._url,
                     exc_info=True)
            raise
        super(VmdkReadHandle, self).close()
        LOG.debug("Closed VMDK read handle for %s.", self._url)

    def __str__(self):
        return "VMDK read handle for %s" % self._url


class ImageReadHandle(object):
    """Read handle for glance images."""

    def __init__(self, glance_read_iter):
        """Initializes the read handle with given parameters.

        :param glance_read_iter: iterator to read data from glance image
        """
        self._glance_read_iter = glance_read_iter
        self._iter = self.get_next()

    def read(self, chunk_size):
        """Read an item from the image data iterator.

        The input chunk size is ignored since the client ImageBodyIterator
        uses its own chunk size.
        """
        try:
            data = next(self._iter)
            return data
        except StopIteration:
            LOG.debug("Completed reading data from the image iterator.")
            return ""

    def get_next(self):
        """Get the next item from the image iterator."""
        for data in self._glance_read_iter:
            yield data

    def close(self):
        """Close the read handle.

        This is a NOP.
        """
        pass

    def __str__(self):
        return "Image read handle"
