# vim: tabstop=4 shiftwidth=4 softtabstop=4

# Copyright 2013 VMware
# All rights reserved.
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
#
# @author: Salvatore Orlando, VMware
#

import mock
from oslo.config import cfg
from webob import exc as web_exc
import webtest

from neutron.api import extensions
from neutron.api.v2 import attributes
from neutron.api.v2 import router
from neutron import context
from neutron.extensions import providernet as pnet
from neutron.manager import NeutronManager
from neutron.openstack.common import uuidutils
from neutron import quota
from neutron.tests.unit import test_api_v2
from neutron.tests.unit import test_extensions
from neutron.tests.unit import testlib_api


class ProviderExtensionManager(object):

    def get_resources(self):
        return []

    def get_actions(self):
        return []

    def get_request_extensions(self):
        return []

    def get_extended_resources(self, version):
        return pnet.get_extended_resources(version)


class ProvidernetExtensionTestCase(testlib_api.WebTestCase):
    fmt = 'json'

    def setUp(self):
        super(ProvidernetExtensionTestCase, self).setUp()

        plugin = 'neutron.neutron_plugin_base_v2.NeutronPluginBaseV2'

        # Ensure existing ExtensionManager is not used
        extensions.PluginAwareExtensionManager._instance = None

        # Save the global RESOURCE_ATTRIBUTE_MAP
        self.saved_attr_map = {}
        for resource, attrs in attributes.RESOURCE_ATTRIBUTE_MAP.iteritems():
            self.saved_attr_map[resource] = attrs.copy()

        # Update the plugin and extensions path
        self.setup_coreplugin(plugin)
        cfg.CONF.set_override('allow_pagination', True)
        cfg.CONF.set_override('allow_sorting', True)
        self._plugin_patcher = mock.patch(plugin, autospec=True)
        self.plugin = self._plugin_patcher.start()
        # Ensure Quota checks never fail because of mock
        instance = self.plugin.return_value
        instance.get_networks_count.return_value = 1
        # Instantiate mock plugin and enable the 'provider' extension
        NeutronManager.get_plugin().supported_extension_aliases = (
            ["provider"])
        ext_mgr = ProviderExtensionManager()
        self.ext_mdw = test_extensions.setup_extensions_middleware(ext_mgr)
        self.addCleanup(self._plugin_patcher.stop)
        self.addCleanup(self._restore_attribute_map)
        self.api = webtest.TestApp(router.APIRouter())

        quota.QUOTAS._driver = None
        cfg.CONF.set_override('quota_driver', 'neutron.quota.ConfDriver',
                              group='QUOTAS')

    def _restore_attribute_map(self):
        # Restore the global RESOURCE_ATTRIBUTE_MAP
        attributes.RESOURCE_ATTRIBUTE_MAP = self.saved_attr_map

    def _prepare_net_data(self):
        return {'name': 'net1',
                pnet.NETWORK_TYPE: 'sometype',
                pnet.PHYSICAL_NETWORK: 'physnet',
                pnet.SEGMENTATION_ID: 666}

    def _put_network_with_provider_attrs(self, ctx, expect_errors=False):
        data = self._prepare_net_data()
        env = {'neutron.context': ctx}
        instance = self.plugin.return_value
        instance.get_network.return_value = {'tenant_id': ctx.tenant_id,
                                             'shared': False}
        net_id = uuidutils.generate_uuid()
        res = self.api.put(test_api_v2._get_path('networks',
                                                 id=net_id,
                                                 fmt=self.fmt),
                           self.serialize({'network': data}),
                           extra_environ=env,
                           expect_errors=expect_errors)
        return res, data, net_id

    def _post_network_with_provider_attrs(self, ctx, expect_errors=False):
        data = self._prepare_net_data()
        env = {'neutron.context': ctx}
        res = self.api.post(test_api_v2._get_path('networks', fmt=self.fmt),
                            self.serialize({'network': data}),
                            content_type='application/' + self.fmt,
                            extra_environ=env,
                            expect_errors=expect_errors)
        return res, data

    def test_network_create_with_provider_attrs(self):
        ctx = context.get_admin_context()
        ctx.tenant_id = 'an_admin'
        res, data = self._post_network_with_provider_attrs(ctx)
        instance = self.plugin.return_value
        exp_input = {'network': data}
        exp_input['network'].update({'admin_state_up': True,
                                     'tenant_id': 'an_admin',
                                     'shared': False})
        instance.create_network.assert_called_with(mock.ANY,
                                                   network=exp_input)
        self.assertEqual(res.status_int, web_exc.HTTPCreated.code)

    def test_network_update_with_provider_attrs(self):
        ctx = context.get_admin_context()
        ctx.tenant_id = 'an_admin'
        res, data, net_id = self._put_network_with_provider_attrs(ctx)
        instance = self.plugin.return_value
        exp_input = {'network': data}
        instance.update_network.assert_called_with(mock.ANY,
                                                   net_id,
                                                   network=exp_input)
        self.assertEqual(res.status_int, web_exc.HTTPOk.code)

    def test_network_create_with_provider_attrs_noadmin_returns_403(self):
        tenant_id = 'no_admin'
        ctx = context.Context('', tenant_id, is_admin=False)
        res, _1 = self._post_network_with_provider_attrs(ctx, True)
        self.assertEqual(res.status_int, web_exc.HTTPForbidden.code)

    def test_network_update_with_provider_attrs_noadmin_returns_404(self):
        tenant_id = 'no_admin'
        ctx = context.Context('', tenant_id, is_admin=False)
        res, _1, _2 = self._put_network_with_provider_attrs(ctx, True)
        self.assertEqual(res.status_int, web_exc.HTTPNotFound.code)
