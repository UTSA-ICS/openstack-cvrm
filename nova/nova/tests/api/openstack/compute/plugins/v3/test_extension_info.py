# Copyright 2013 IBM Corp.
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

from nova.api.openstack.compute import plugins
from nova.api.openstack.compute.plugins.v3 import extension_info
from nova import exception
from nova import policy
from nova import test
from nova.tests.api.openstack import fakes


class fake_extension(object):
    def __init__(self, name, alias, description, version):
        self.name = name
        self.alias = alias
        self.__doc__ = description
        self.version = version


fake_extensions = {
    'ext1-alias': fake_extension('ext1', 'ext1-alias', 'ext1 description', 1),
    'ext2-alias': fake_extension('ext2', 'ext2-alias', 'ext2 description', 2),
    'ext3-alias': fake_extension('ext3', 'ext3-alias', 'ext3 description', 1)
}


def fake_policy_enforce(context, action, target, do_raise=True):
    return True


def fake_policy_enforce_selective(context, action, target, do_raise=True):
    if action == 'compute_extension:v3:ext1-alias:discoverable':
        raise exception.NotAuthorized
    else:
        return True


class ExtensionInfoTest(test.NoDBTestCase):

    def setUp(self):
        super(ExtensionInfoTest, self).setUp()
        ext_info = plugins.LoadedExtensionInfo()
        ext_info.extensions = fake_extensions
        self.controller = extension_info.ExtensionInfoController(ext_info)

    def test_extension_info_list(self):
        self.stubs.Set(policy, 'enforce', fake_policy_enforce)
        req = fakes.HTTPRequestV3.blank('/extensions')
        res_dict = self.controller.index(req)
        self.assertEqual(3, len(res_dict['extensions']))
        for e in res_dict['extensions']:
            self.assertIn(e['alias'], fake_extensions)
            self.assertEqual(e['name'], fake_extensions[e['alias']].name)
            self.assertEqual(e['alias'], fake_extensions[e['alias']].alias)
            self.assertEqual(e['description'],
                             fake_extensions[e['alias']].__doc__)
            self.assertEqual(e['version'],
                             fake_extensions[e['alias']].version)

    def test_extension_info_show(self):
        self.stubs.Set(policy, 'enforce', fake_policy_enforce)
        req = fakes.HTTPRequestV3.blank('/extensions/ext1-alias')
        res_dict = self.controller.show(req, 'ext1-alias')
        self.assertEqual(1, len(res_dict))
        self.assertEqual(res_dict['extension']['name'],
                         fake_extensions['ext1-alias'].name)
        self.assertEqual(res_dict['extension']['alias'],
                         fake_extensions['ext1-alias'].alias)
        self.assertEqual(res_dict['extension']['description'],
                         fake_extensions['ext1-alias'].__doc__)
        self.assertEqual(res_dict['extension']['version'],
                         fake_extensions['ext1-alias'].version)

    def test_extension_info_list_not_all_discoverable(self):
        self.stubs.Set(policy, 'enforce', fake_policy_enforce_selective)
        req = fakes.HTTPRequestV3.blank('/extensions')
        res_dict = self.controller.index(req)
        self.assertEqual(2, len(res_dict['extensions']))
        for e in res_dict['extensions']:
            self.assertNotEqual('ext1-alias', e['alias'])
            self.assertIn(e['alias'], fake_extensions)
            self.assertEqual(e['name'], fake_extensions[e['alias']].name)
            self.assertEqual(e['alias'], fake_extensions[e['alias']].alias)
            self.assertEqual(e['description'],
                             fake_extensions[e['alias']].__doc__)
            self.assertEqual(e['version'],
                             fake_extensions[e['alias']].version)
