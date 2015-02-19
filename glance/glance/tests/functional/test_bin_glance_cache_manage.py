# Copyright 2011 OpenStack Foundation
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

"""Functional test case that utilizes the bin/glance-cache-manage CLI tool"""

import datetime
import hashlib
import httplib2
import os
import sys

from six.moves import xrange

from glance.openstack.common import jsonutils
from glance.openstack.common import units
from glance.tests import functional
from glance.tests.utils import execute
from glance.tests.utils import minimal_headers

FIVE_KB = 5 * units.Ki


class TestBinGlanceCacheManage(functional.FunctionalTest):
    """Functional tests for the bin/glance CLI tool"""

    def setUp(self):
        self.image_cache_driver = "sqlite"

        super(TestBinGlanceCacheManage, self).setUp()

        self.api_server.deployment_flavor = "cachemanagement"

        # NOTE(sirp): This is needed in case we are running the tests under an
        # environment in which OS_AUTH_STRATEGY=keystone. The test server we
        # spin up won't have keystone support, so we need to switch to the
        # NoAuth strategy.
        os.environ['OS_AUTH_STRATEGY'] = 'noauth'
        os.environ['OS_AUTH_URL'] = ''

    def add_image(self, name):
        """
        Adds an image with supplied name and returns the newly-created
        image identifier.
        """
        image_data = "*" * FIVE_KB
        headers = minimal_headers(name)
        path = "http://%s:%d/v1/images" % ("127.0.0.1", self.api_port)
        http = httplib2.Http()
        response, content = http.request(path, 'POST', headers=headers,
                                         body=image_data)
        self.assertEqual(response.status, 201)
        data = jsonutils.loads(content)
        self.assertEqual(data['image']['checksum'],
                         hashlib.md5(image_data).hexdigest())
        self.assertEqual(data['image']['size'], FIVE_KB)
        self.assertEqual(data['image']['name'], name)
        self.assertEqual(data['image']['is_public'], True)
        return data['image']['id']

    def is_image_cached(self, image_id):
        """
        Return True if supplied image ID is cached, False otherwise
        """
        exe_cmd = '%s -m glance.cmd.cache_manage' % sys.executable
        cmd = "%s --port=%d list-cached" % (exe_cmd, self.api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        return image_id in out

    def iso_date(self, image_id):
        """
        Return True if supplied image ID is cached, False otherwise
        """
        exe_cmd = '%s -m glance.cmd.cache_manage' % sys.executable
        cmd = "%s --port=%d list-cached" % (exe_cmd, self.api_port)

        exitcode, out, err = execute(cmd)

        return datetime.datetime.utcnow().strftime("%Y-%m-%d") in out

    def test_no_cache_enabled(self):
        """
        Test that cache index command works
        """
        self.cleanup()
        self.api_server.deployment_flavor = ''
        self.start_servers()  # Not passing in cache_manage in pipeline...

        api_port = self.api_port

        # Verify decent error message returned
        exe_cmd = '%s -m glance.cmd.cache_manage' % sys.executable
        cmd = "%s --port=%d list-cached" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd, raise_error=False)

        self.assertEqual(1, exitcode)
        self.assertTrue('Cache management middleware not enabled on host'
                        in out.strip())

        self.stop_servers()

    def test_cache_index(self):
        """
        Test that cache index command works
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        api_port = self.api_port

        # Verify no cached images
        exe_cmd = '%s -m glance.cmd.cache_manage' % sys.executable
        cmd = "%s --port=%d list-cached" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue('No cached images' in out.strip())

        ids = {}

        # Add a few images and cache the second one of them
        # by GETing the image...
        for x in xrange(4):
            ids[x] = self.add_image("Image%s" % x)

        path = "http://%s:%d/v1/images/%s" % ("127.0.0.1", api_port,
                                              ids[1])
        http = httplib2.Http()
        response, content = http.request(path, 'GET')
        self.assertEqual(response.status, 200)

        self.assertTrue(self.is_image_cached(ids[1]),
                        "%s is not cached." % ids[1])

        self.assertTrue(self.iso_date(ids[1]))

        self.stop_servers()

    def test_queue(self):
        """
        Test that we can queue and fetch images using the
        CLI utility
        """
        self.cleanup()
        self.start_servers(**self.__dict__.copy())

        api_port = self.api_port

        # Verify no cached images
        exe_cmd = '%s -m glance.cmd.cache_manage' % sys.executable
        cmd = "%s --port=%d list-cached" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue('No cached images' in out.strip())

        # Verify no queued images
        cmd = "%s --port=%d list-queued" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue('No queued images' in out.strip())

        ids = {}

        # Add a few images and cache the second one of them
        # by GETing the image...
        for x in xrange(4):
            ids[x] = self.add_image("Image%s" % x)

        # Queue second image and then cache it
        cmd = "%s --port=%d --force queue-image %s" % (
            exe_cmd, api_port, ids[1])

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)

        # Verify queued second image
        cmd = "%s --port=%d list-queued" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue(ids[1] in out, 'Image %s was not queued!' % ids[1])

        # Cache images in the queue by running the prefetcher
        cache_config_filepath = os.path.join(self.test_dir, 'etc',
                                             'glance-cache.conf')
        cache_file_options = {
            'image_cache_dir': self.api_server.image_cache_dir,
            'image_cache_driver': self.image_cache_driver,
            'registry_port': self.registry_server.bind_port,
            'log_file': os.path.join(self.test_dir, 'cache.log'),
            'metadata_encryption_key': "012345678901234567890123456789ab"
        }
        with open(cache_config_filepath, 'w') as cache_file:
            cache_file.write("""[DEFAULT]
debug = True
verbose = True
image_cache_dir = %(image_cache_dir)s
image_cache_driver = %(image_cache_driver)s
registry_host = 127.0.0.1
registry_port = %(registry_port)s
metadata_encryption_key = %(metadata_encryption_key)s
log_file = %(log_file)s
""" % cache_file_options)

        cmd = ("%s -m glance.cmd.cache_prefetcher --config-file %s" %
               (sys.executable, cache_config_filepath))

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertEqual('', out.strip(), out)

        # Verify no queued images
        cmd = "%s --port=%d list-queued" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue('No queued images' in out.strip())

        # Verify second image now cached
        cmd = "%s --port=%d list-cached" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue(ids[1] in out, 'Image %s was not cached!' % ids[1])

        # Queue third image and then delete it from queue
        cmd = "%s --port=%d --force queue-image %s" % (
            exe_cmd, api_port, ids[2])

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)

        # Verify queued third image
        cmd = "%s --port=%d list-queued" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue(ids[2] in out, 'Image %s was not queued!' % ids[2])

        # Delete the image from the queue
        cmd = ("%s --port=%d --force "
               "delete-queued-image %s") % (exe_cmd, api_port, ids[2])

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)

        # Verify no queued images
        cmd = "%s --port=%d list-queued" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue('No queued images' in out.strip())

        # Queue all images
        for x in xrange(4):
            cmd = ("%s --port=%d --force "
                   "queue-image %s") % (exe_cmd, api_port, ids[x])

            exitcode, out, err = execute(cmd)

            self.assertEqual(0, exitcode)

        # Verify queued third image
        cmd = "%s --port=%d list-queued" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue('Found 3 queued images' in out)

        # Delete the image from the queue
        cmd = ("%s --port=%d --force "
               "delete-all-queued-images") % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)

        # Verify nothing in queue anymore
        cmd = "%s --port=%d list-queued" % (exe_cmd, api_port)

        exitcode, out, err = execute(cmd)

        self.assertEqual(0, exitcode)
        self.assertTrue('No queued images' in out.strip())

        # verify two image id when queue-image
        cmd = ("%s --port=%d --force "
               "queue-image %s %s") % (exe_cmd, api_port, ids[0], ids[1])

        exitcode, out, err = execute(cmd, raise_error=False)

        self.assertEqual(1, exitcode)
        self.assertTrue('Please specify one and only ID of '
                        'the image you wish to ' in out.strip())

        # verify two image id when delete-queued-image
        cmd = ("%s --port=%d --force delete-queued-image "
               "%s %s") % (exe_cmd, api_port, ids[0], ids[1])

        exitcode, out, err = execute(cmd, raise_error=False)

        self.assertEqual(1, exitcode)
        self.assertTrue('Please specify one and only ID of '
                        'the image you wish to ' in out.strip())

        # verify two image id when delete-cached-image
        cmd = ("%s --port=%d --force delete-cached-image "
               "%s %s") % (exe_cmd, api_port, ids[0], ids[1])

        exitcode, out, err = execute(cmd, raise_error=False)

        self.assertEqual(1, exitcode)
        self.assertTrue('Please specify one and only ID of '
                        'the image you wish to ' in out.strip())

        self.stop_servers()
