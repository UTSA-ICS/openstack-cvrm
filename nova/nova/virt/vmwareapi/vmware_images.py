# Copyright (c) 2012 VMware, Inc.
# Copyright (c) 2011 Citrix Systems, Inc.
# Copyright 2011 OpenStack Foundation
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
Utility functions for Image transfer.
"""

import os

from nova import exception
from nova.image import glance
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.virt.vmwareapi import io_util
from nova.virt.vmwareapi import read_write_util

LOG = logging.getLogger(__name__)

QUEUE_BUFFER_SIZE = 10


def start_transfer(context, read_file_handle, data_size,
        write_file_handle=None, image_service=None, image_id=None,
        image_meta=None):
    """Start the data transfer from the reader to the writer.
    Reader writes to the pipe and the writer reads from the pipe. This means
    that the total transfer time boils down to the slower of the read/write
    and not the addition of the two times.
    """

    if not image_meta:
        image_meta = {}

    # The pipe that acts as an intermediate store of data for reader to write
    # to and writer to grab from.
    thread_safe_pipe = io_util.ThreadSafePipe(QUEUE_BUFFER_SIZE, data_size)
    # The read thread. In case of glance it is the instance of the
    # GlanceFileRead class. The glance client read returns an iterator
    # and this class wraps that iterator to provide datachunks in calls
    # to read.
    read_thread = io_util.IOThread(read_file_handle, thread_safe_pipe)

    # In case of Glance - VMware transfer, we just need a handle to the
    # HTTP Connection that is to send transfer data to the VMware datastore.
    if write_file_handle:
        write_thread = io_util.IOThread(thread_safe_pipe, write_file_handle)
    # In case of VMware - Glance transfer, we relinquish VMware HTTP file read
    # handle to Glance Client instance, but to be sure of the transfer we need
    # to be sure of the status of the image on glance changing to active.
    # The GlanceWriteThread handles the same for us.
    elif image_service and image_id:
        write_thread = io_util.GlanceWriteThread(context, thread_safe_pipe,
                image_service, image_id, image_meta)
    # Start the read and write threads.
    read_event = read_thread.start()
    write_event = write_thread.start()
    try:
        # Wait on the read and write events to signal their end
        read_event.wait()
        write_event.wait()
    except Exception as exc:
        # In case of any of the reads or writes raising an exception,
        # stop the threads so that we un-necessarily don't keep the other one
        # waiting.
        read_thread.stop()
        write_thread.stop()

        # Log and raise the exception.
        LOG.exception(exc)
        raise exception.NovaException(exc)
    finally:
        # No matter what, try closing the read and write handles, if it so
        # applies.
        read_file_handle.close()
        if write_file_handle:
            write_file_handle.close()


def upload_iso_to_datastore(iso_path, instance, **kwargs):
    LOG.debug(_("Uploading iso %s to datastore") % iso_path,
              instance=instance)
    with open(iso_path, 'r') as iso_file:
        write_file_handle = read_write_util.VMwareHTTPWriteFile(
            kwargs.get("host"),
            kwargs.get("data_center_name"),
            kwargs.get("datastore_name"),
            kwargs.get("cookies"),
            kwargs.get("file_path"),
            os.fstat(iso_file.fileno()).st_size)

        LOG.debug(_("Uploading iso of size : %s ") %
                  os.fstat(iso_file.fileno()).st_size)
        block_size = 0x10000
        data = iso_file.read(block_size)
        while len(data) > 0:
            write_file_handle.write(data)
            data = iso_file.read(block_size)
        write_file_handle.close()

    LOG.debug(_("Uploaded iso %s to datastore") % iso_path,
              instance=instance)


def fetch_image(context, image, instance, **kwargs):
    """Download image from the glance image server."""
    LOG.debug(_("Downloading image %s from glance image server") % image,
              instance=instance)
    (image_service, image_id) = glance.get_remote_image_service(context, image)
    metadata = image_service.show(context, image_id)
    file_size = int(metadata['size'])
    read_iter = image_service.download(context, image_id)
    read_file_handle = read_write_util.GlanceFileRead(read_iter)
    write_file_handle = read_write_util.VMwareHTTPWriteFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"),
                                file_size)
    start_transfer(context, read_file_handle, file_size,
                   write_file_handle=write_file_handle)
    LOG.debug(_("Downloaded image %s from glance image server") % image,
              instance=instance)


def upload_image(context, image, instance, **kwargs):
    """Upload the snapshotted vm disk file to Glance image server."""
    LOG.debug(_("Uploading image %s to the Glance image server") % image,
              instance=instance)
    read_file_handle = read_write_util.VMwareHTTPReadFile(
                                kwargs.get("host"),
                                kwargs.get("data_center_name"),
                                kwargs.get("datastore_name"),
                                kwargs.get("cookies"),
                                kwargs.get("file_path"))
    file_size = read_file_handle.get_size()
    (image_service, image_id) = glance.get_remote_image_service(context, image)
    metadata = image_service.show(context, image_id)

    # The properties and other fields that we need to set for the image.
    image_metadata = {"disk_format": "vmdk",
                      "is_public": "false",
                      "name": metadata['name'],
                      "status": "active",
                      "container_format": "bare",
                      "size": file_size,
                      "properties": {"vmware_adaptertype":
                                            kwargs.get("adapter_type"),
                                     "vmware_disktype":
                                            kwargs.get("disk_type"),
                                     "vmware_ostype": kwargs.get("os_type"),
                                     "vmware_image_version":
                                            kwargs.get("image_version"),
                                     "owner_id": instance['project_id']}}
    start_transfer(context, read_file_handle, file_size,
                   image_service=image_service,
                   image_id=image_id, image_meta=image_metadata)
    LOG.debug(_("Uploaded image %s to the Glance image server") % image,
              instance=instance)


def get_vmdk_size_and_properties(context, image, instance):
    """Get size of the vmdk file that is to be downloaded for attach in spawn.
    Need this to create the dummy virtual disk for the meta-data file. The
    geometry of the disk created depends on the size.
    """

    LOG.debug(_("Getting image size for the image %s") % image,
              instance=instance)
    (image_service, image_id) = glance.get_remote_image_service(context, image)
    meta_data = image_service.show(context, image_id)
    size, properties = meta_data["size"], meta_data["properties"]
    LOG.debug(_("Got image size of %(size)s for the image %(image)s"),
              {'size': size, 'image': image}, instance=instance)
    return size, properties
