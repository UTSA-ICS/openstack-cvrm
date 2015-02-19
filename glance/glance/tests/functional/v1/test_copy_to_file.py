# Copyright 2011 OpenStack Foundation
# Copyright 2012 Red Hat, Inc
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
Tests copying images to a Glance API server which uses a filesystem-
based storage backend.
"""

import hashlib
import httplib2
import tempfile
import time

from six.moves import xrange

from glance.openstack.common import jsonutils
from glance.openstack.common import units
from glance.tests import functional
from glance.tests.functional.store_utils import get_http_uri
from glance.tests.functional.store_utils import setup_http
from glance.tests.utils import skip_if_disabled

FIVE_KB = 5 * units.Ki


class TestCopyToFile(functional.FunctionalTest):

    """
    Functional tests for copying images from the HTTP storage
    backend to file
    """

    def _do_test_copy_from(self, from_store, get_uri):
        """
        Ensure we can copy from an external image in from_store.
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())
        setup_http(self)

        # POST /images with public image to be stored in from_store,
        # to stand in for the 'external' image
        image_data = "*" * FIVE_KB
        headers = {'Content-Type': 'application/octet-stream',
                   'X-Image-Meta-Name': 'external',
                   'X-Image-Meta-Store': from_store,
                   'X-Image-Meta-disk_format': 'raw',
                   'X-Image-Meta-container_format': 'ovf',
                   'X-Image-Meta-Is-Public': 'True'}
        path = "http://%s:%d/v1/images" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=image_data)
        self.assertEqual(response.status, 201, content)
        data = jsonutils.loads(content)

        original_image_id = data['image']['id']

        copy_from = get_uri(self, original_image_id)

        # POST /images with public image copied from_store (to file)
        headers = {'X-Image-Meta-Name': 'copied',
                   'X-Image-Meta-disk_format': 'raw',
                   'X-Image-Meta-container_format': 'ovf',
                   'X-Image-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/images" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(response.status, 201, content)
        data = jsonutils.loads(content)

        copy_image_id = data['image']['id']
        self.assertNotEqual(copy_image_id, original_image_id)

        # GET image and make sure image content is as expected
        path = "http://%s:%d/v1/images/%s" % ("127.0.0.1", self.api_port,
                                              copy_image_id)

        def _await_status(expected_status):
            for i in xrange(100):
                time.sleep(0.01)
                http = httplib2.Http()
                response, content = http.request(path, 'HEAD')
                self.assertEqual(response.status, 200)
                if response['x-image-meta-status'] == expected_status:
                    return
            self.fail('unexpected image status %s' %
                      response['x-image-meta-status'])
        _await_status('active')

        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['content-length'], str(FIVE_KB))

        self.assertEqual(content, "*" * FIVE_KB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_KB).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], "copied")

        # DELETE original image
        path = "http://%s:%d/v1/images/%s" % ("127.0.0.1", self.api_port,
                                              original_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        # GET image again to make sure the existence of the original
        # image in from_store is not depended on
        path = "http://%s:%d/v1/images/%s" % ("127.0.0.1", self.api_port,
                                              copy_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)
        self.assertEqual(response['content-length'], str(FIVE_KB))

        self.assertEqual(content, "*" * FIVE_KB)
        self.assertEqual(hashlib.md5(content).hexdigest(),
                         hashlib.md5("*" * FIVE_KB).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], "copied")

        # DELETE copied image
        path = "http://%s:%d/v1/images/%s" % ("127.0.0.1", self.api_port,
                                              copy_image_id)
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        self.stop_servers()

    @skip_if_disabled
    def test_copy_from_http_store(self):
        """
        Ensure we can copy from an external image in HTTP store.
        """
        self._do_test_copy_from('file', get_http_uri)

    @skip_if_disabled
    def _do_test_copy_from_http(self, exists):
        """
        Ensure we can copy from an external image in HTTP.

        :param exists: True iff the external source image exists
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        setup_http(self)

        uri = get_http_uri(self, 'foobar')
        copy_from = uri if exists else uri.replace('images', 'snafu')

        # POST /images with public image copied from HTTP (to file)
        headers = {'X-Image-Meta-Name': 'copied',
                   'X-Image-Meta-disk_format': 'raw',
                   'X-Image-Meta-container_format': 'ovf',
                   'X-Image-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/images" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(response.status, 201, content)
        data = jsonutils.loads(content)

        copy_image_id = data['image']['id']
        self.assertEqual(data['image']['status'], 'queued', content)

        path = "http://%s:%d/v1/images/%s" % ("127.0.0.1", self.api_port,
                                              copy_image_id)

        def _await_status(expected_status):
            for i in xrange(100):
                time.sleep(0.01)
                http = httplib2.Http()
                response, content = http.request(path, 'HEAD')
                self.assertEqual(response.status, 200)
                if response['x-image-meta-status'] == expected_status:
                    return
            self.fail('unexpected image status %s' %
                      response['x-image-meta-status'])

        _await_status('active' if exists else 'killed')

        # GET image and make sure image content is as expected
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200 if exists else 404)

        if exists:
            self.assertEqual(response['content-length'], str(FIVE_KB))
            self.assertEqual(content, "*" * FIVE_KB)
            self.assertEqual(hashlib.md5(content).hexdigest(),
                             hashlib.md5("*" * FIVE_KB).hexdigest())

        # DELETE copied image
        http = httplib2.Http()
        response, content = http.request(path, 'DELETE')
        self.assertEqual(response.status, 200)

        self.stop_servers()

    @skip_if_disabled
    def test_copy_from_http_exists(self):
        self._do_test_copy_from_http(True)

    @skip_if_disabled
    def test_copy_from_http_nonexistent(self):
        self._do_test_copy_from_http(False)

    @skip_if_disabled
    def test_copy_from_file(self):
        """
        Ensure we can't copy from file
        """
        self.cleanup()

        self.start_servers(**self.__dict__.copy())

        with tempfile.NamedTemporaryFile() as image_file:
            image_file.write("XXX")
            image_file.flush()
            copy_from = 'file://' + image_file.name

        # POST /images with public image copied from file (to file)
        headers = {'X-Image-Meta-Name': 'copied',
                   'X-Image-Meta-disk_format': 'raw',
                   'X-Image-Meta-container_format': 'ovf',
                   'X-Image-Meta-Is-Public': 'True',
                   'X-Glance-API-Copy-From': copy_from}
        path = "http://%s:%d/v1/images" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers)
        self.assertEqual(response.status, 400, content)

        expected = 'External sourcing not supported for store ' + copy_from
        msg = 'expected "%s" in "%s"' % (expected, content)
        self.assertTrue(expected in content, msg)

        self.stop_servers()
