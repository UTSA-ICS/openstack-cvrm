# Copyright 2013 Metacloud
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import copy

from dogpile.cache import api
from dogpile.cache import proxy

from keystone.common import cache
from keystone import config
from keystone import exception
from keystone import tests


CONF = config.CONF
NO_VALUE = api.NO_VALUE


def _copy_value(value):
    if value is not NO_VALUE:
        value = copy.deepcopy(value)
    return value


# NOTE(morganfainberg): WARNING - It is not recommended to use the Memory
# backend for dogpile.cache in a real deployment under any circumstances. The
# backend does no cleanup of expired values and therefore will leak memory. The
# backend is not implemented in a way to share data across processes (e.g.
# Keystone in HTTPD.  This proxy is a hack to get around the lack of isolation
# of values in memory.  Currently it blindly stores and retrieves the values
# from the cache, and modifications to dicts/lists/etc returned can result in
# changes to the cached values.  In short, do not use the dogpile.cache.memory
# backend unless you are running tests or expecting odd/strange results.
class CacheIsolatingProxy(proxy.ProxyBackend):
    """Proxy that forces a memory copy of stored values.
    The default in-memory cache-region does not perform a copy on values it
    is meant to cache.  Therefore if the value is modified after set or after
    get, the cached value also is modified.  This proxy does a copy as the last
    thing before storing data.
    """
    def get(self, key):
        return _copy_value(self.proxied.get(key))

    def set(self, key, value):
        self.proxied.set(key, _copy_value(value))


class TestProxy(proxy.ProxyBackend):
    def get(self, key):
        value = _copy_value(self.proxied.get(key))
        if value is not NO_VALUE:
            if isinstance(value[0], TestProxyValue):
                value[0].cached = True
        return value


class TestProxyValue(object):
    def __init__(self, value):
        self.value = value
        self.cached = False


class CacheRegionTest(tests.TestCase):

    def setUp(self):
        super(CacheRegionTest, self).setUp()
        self.region = cache.make_region()
        cache.configure_cache_region(self.region)
        self.region.wrap(TestProxy)
        self.test_value = TestProxyValue('Decorator Test')

    def _add_test_caching_option(self):
        self.config_fixture.register_opt(
            config.config.cfg.BoolOpt('caching', default=True), group='cache')

    def _get_cacheable_function(self):
        SHOULD_CACHE_FN = cache.should_cache_fn('cache')

        @self.region.cache_on_arguments(should_cache_fn=SHOULD_CACHE_FN)
        def cacheable_function(value):
            return value

        return cacheable_function

    def test_region_built_with_proxy_direct_cache_test(self):
        # Verify cache regions are properly built with proxies.
        test_value = TestProxyValue('Direct Cache Test')
        self.region.set('cache_test', test_value)
        cached_value = self.region.get('cache_test')
        self.assertTrue(cached_value.cached)

    def test_cache_region_no_error_multiple_config(self):
        # Verify configuring the CacheRegion again doesn't error.
        cache.configure_cache_region(self.region)
        cache.configure_cache_region(self.region)

    def test_should_cache_fn_global_cache_enabled(self):
        # Verify should_cache_fn generates a sane function for subsystem and
        # functions as expected with caching globally enabled.
        cacheable_function = self._get_cacheable_function()

        self.config_fixture.config(group='cache', enabled=True)
        cacheable_function(self.test_value)
        cached_value = cacheable_function(self.test_value)
        self.assertTrue(cached_value.cached)

    def test_should_cache_fn_global_cache_disabled(self):
        # Verify should_cache_fn generates a sane function for subsystem and
        # functions as expected with caching globally disabled.
        cacheable_function = self._get_cacheable_function()

        self.config_fixture.config(group='cache', enabled=False)
        cacheable_function(self.test_value)
        cached_value = cacheable_function(self.test_value)
        self.assertFalse(cached_value.cached)

    def test_should_cache_fn_global_cache_disabled_section_cache_enabled(self):
        # Verify should_cache_fn generates a sane function for subsystem and
        # functions as expected with caching globally disabled and the specific
        # section caching enabled.
        cacheable_function = self._get_cacheable_function()

        self._add_test_caching_option()
        self.config_fixture.config(group='cache', enabled=False)
        self.config_fixture.config(group='cache', caching=True)

        cacheable_function(self.test_value)
        cached_value = cacheable_function(self.test_value)
        self.assertFalse(cached_value.cached)

    def test_should_cache_fn_global_cache_enabled_section_cache_disabled(self):
        # Verify should_cache_fn generates a sane function for subsystem and
        # functions as expected with caching globally enabled and the specific
        # section caching disabled.
        cacheable_function = self._get_cacheable_function()

        self._add_test_caching_option()
        self.config_fixture.config(group='cache', enabled=True)
        self.config_fixture.config(group='cache', caching=False)

        cacheable_function(self.test_value)
        cached_value = cacheable_function(self.test_value)
        self.assertFalse(cached_value.cached)

    def test_should_cache_fn_global_cache_enabled_section_cache_enabled(self):
        # Verify should_cache_fn generates a sane function for subsystem and
        # functions as expected with caching globally enabled and the specific
        # section caching enabled.
        cacheable_function = self._get_cacheable_function()

        self._add_test_caching_option()
        self.config_fixture.config(group='cache', enabled=True)
        self.config_fixture.config(group='cache', caching=True)

        cacheable_function(self.test_value)
        cached_value = cacheable_function(self.test_value)
        self.assertTrue(cached_value.cached)

    def test_cache_dictionary_config_builder(self):
        """Validate we build a sane dogpile.cache dictionary config."""
        self.config_fixture.config(group='cache',
                                   config_prefix='test_prefix',
                                   backend='some_test_backend',
                                   expiration_time=86400,
                                   backend_argument=['arg1:test',
                                                     'arg2:test:test',
                                                     'arg3.invalid'])

        config_dict = cache.build_cache_config()
        self.assertEqual(
            CONF.cache.backend, config_dict['test_prefix.backend'])
        self.assertEqual(
            CONF.cache.expiration_time,
            config_dict['test_prefix.expiration_time'])
        self.assertEqual('test', config_dict['test_prefix.arguments.arg1'])
        self.assertEqual('test:test',
                         config_dict['test_prefix.arguments.arg2'])
        self.assertFalse('test_prefix.arguments.arg3' in config_dict)

    def test_cache_debug_proxy(self):
        single_value = 'Test Value'
        single_key = 'testkey'
        multi_values = {'key1': 1, 'key2': 2, 'key3': 3}

        self.region.set(single_key, single_value)
        self.assertEqual(single_value, self.region.get(single_key))

        self.region.delete(single_key)
        self.assertEqual(NO_VALUE, self.region.get(single_key))

        self.region.set_multi(multi_values)
        cached_values = self.region.get_multi(multi_values.keys())
        for value in multi_values.values():
            self.assertIn(value, cached_values)
        self.assertEqual(len(multi_values.values()), len(cached_values))

        self.region.delete_multi(multi_values.keys())
        for value in self.region.get_multi(multi_values.keys()):
            self.assertEqual(NO_VALUE, value)

    def test_configure_non_region_object_raises_error(self):
        self.assertRaises(exception.ValidationError,
                          cache.configure_cache_region,
                          "bogus")


class CacheNoopBackendTest(tests.TestCase):

    def setUp(self):
        super(CacheNoopBackendTest, self).setUp()
        self.region = cache.make_region()
        cache.configure_cache_region(self.region)

    def config_overrides(self):
        super(CacheNoopBackendTest, self).config_overrides()
        self.config_fixture.config(group='cache',
                                   backend='keystone.common.cache.noop')

    def test_noop_backend(self):
        single_value = 'Test Value'
        single_key = 'testkey'
        multi_values = {'key1': 1, 'key2': 2, 'key3': 3}

        self.region.set(single_key, single_value)
        self.assertEqual(NO_VALUE, self.region.get(single_key))

        self.region.set_multi(multi_values)
        cached_values = self.region.get_multi(multi_values.keys())
        self.assertEqual(len(cached_values), len(multi_values.values()))
        for value in cached_values:
            self.assertEqual(NO_VALUE, value)

        # Delete should not raise exceptions
        self.region.delete(single_key)
        self.region.delete_multi(multi_values.keys())
