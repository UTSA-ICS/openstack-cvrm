# Copyright (C) 2013 Yahoo! Inc.
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
import webob

from glance.api import cached_images
from glance.api import policy
from glance.common import exception
from glance import image_cache


class FakePolicyEnforcer(policy.Enforcer):
    def __init__(self):
        self.default_rule = ''
        self.policy_path = ''
        self.policy_file_mtime = None
        self.policy_file_contents = None

    def enforce(self, context, action, target):
        return 'pass'

    def check(rule, target, creds, exc=None, *args, **kwargs):
        return 'pass'

    def _check(self, context, rule, target, *args, **kwargs):
        return 'pass'


class FakeCache(image_cache.ImageCache):
    def __init__(self):
        self.init_driver()
        self.deleted_images = []

    def init_driver(self):
        pass

    def get_cached_images(self):
        return {'id': 'test'}

    def delete_cached_image(self, image_id):
        self.deleted_images.append(image_id)

    def get_queued_images(self):
        return {'test': 'passed'}

    def queue_image(self, image_id):
        return 'pass'

    def delete_queued_image(self, image_id):
        self.deleted_images.append(image_id)


class FakeController(cached_images.Controller):
    def __init__(self):
        self.cache = FakeCache()
        self.policy = FakePolicyEnforcer()


class TestController(testtools.TestCase):
    def test_initialization_without_conf(self):
        self.assertRaises(exception.BadDriverConfiguration,
                          cached_images.Controller)


class TestCachedImages(testtools.TestCase):
    def setUp(self):
        super(TestCachedImages, self).setUp()
        test_controller = FakeController()
        self.controller = test_controller

    def test_get_cached_images(self):
        req = webob.Request.blank('')
        req.context = 'test'
        result = self.controller.get_cached_images(req)
        self.assertEqual({'cached_images': {'id': 'test'}}, result)

    def test_delete_cached_images(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.controller.delete_cached_image(req, image_id='test')
        self.assertEqual(['test'], self.controller.cache.deleted_images)

    def test_get_queued_images(self):
        req = webob.Request.blank('')
        req.context = 'test'
        result = self.controller.get_queued_images(req)
        self.assertEqual({'queued_images': {'test': 'passed'}}, result)

    def test_queue_image(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.controller.queue_image(req, image_id='test1')

    def test_delete_queued_image(self):
        req = webob.Request.blank('')
        req.context = 'test'
        self.controller.delete_queued_image(req, 'deleted_img')
        self.assertEqual(['deleted_img'],
                         self.controller.cache.deleted_images)
