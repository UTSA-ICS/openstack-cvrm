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
Unit tests for classes to invoke VMware VI SOAP calls.
"""

import mock

from oslo import i18n
from oslo.vmware._i18n import _
from oslo.vmware import exceptions
from oslo.vmware import vim
from tests import base


class VimTest(base.TestCase):
    """Test class for Vim."""

    def setUp(self):
        super(VimTest, self).setUp()
        patcher = mock.patch('suds.client.Client')
        self.addCleanup(patcher.stop)
        self.SudsClientMock = patcher.start()
        back_use_lazy = i18n._lazy.USE_LAZY
        i18n.enable_lazy()
        self.addCleanup(self._restore_use_lazy, back_use_lazy)

    def _restore_use_lazy(self, back_use_lazy):
        i18n._lazy.USE_LAZY = back_use_lazy

    @mock.patch.object(vim.Vim, '__getattr__', autospec=True)
    def test_service_content(self, getattr_mock):
        getattr_ret = mock.Mock()
        getattr_mock.side_effect = lambda *args: getattr_ret
        vim_obj = vim.Vim()
        vim_obj.service_content
        getattr_mock.assert_called_once_with(vim_obj, 'RetrieveServiceContent')
        getattr_ret.assert_called_once_with('ServiceInstance')
        self.assertEqual(self.SudsClientMock.return_value, vim_obj.client)
        self.assertEqual(getattr_ret.return_value, vim_obj.service_content)

    def test_exception_summary_exception_as_list(self):
        # assert that if a list is fed to the VimException object
        # that it will error.
        self.assertRaises(ValueError,
                          exceptions.VimException,
                          [], ValueError('foo'))

    def test_exception_summary_string(self):
        e = exceptions.VimException(_("string"), ValueError("foo"))
        string = str(e)
        self.assertEqual("string\nCause: foo", string)

    def test_vim_fault_exception_string(self):
        self.assertRaises(ValueError,
                          exceptions.VimFaultException,
                          "bad", ValueError("argument"))

    def test_vim_fault_exception(self):
        vfe = exceptions.VimFaultException([ValueError("example")], _("cause"))
        string = str(vfe)
        self.assertEqual("cause\nFaults: [ValueError('example',)]", string)

    def test_vim_fault_exception_with_cause_and_details(self):
        vfe = exceptions.VimFaultException([ValueError("example")],
                                           "MyMessage",
                                           "FooBar",
                                           {'foo': 'bar'})
        string = str(vfe)
        self.assertEqual("MyMessage\n"
                         "Cause: FooBar\n"
                         "Faults: [ValueError('example',)]\n"
                         "Details: {'foo': 'bar'}",
                         string)

    def test_configure_non_default_host_port(self):
        vim_obj = vim.Vim('https', 'www.test.com', 12345)
        self.assertEqual('https://www.test.com:12345/sdk/vimService.wsdl',
                         vim_obj.wsdl_url)
        self.assertEqual('https://www.test.com:12345/sdk',
                         vim_obj.soap_url)

    def test_configure_ipv6(self):
        vim_obj = vim.Vim('https', '::1')
        self.assertEqual('https://[::1]/sdk/vimService.wsdl',
                         vim_obj.wsdl_url)
        self.assertEqual('https://[::1]/sdk',
                         vim_obj.soap_url)

    def test_configure_ipv6_and_non_default_host_port(self):
        vim_obj = vim.Vim('https', '::1', 12345)
        self.assertEqual('https://[::1]:12345/sdk/vimService.wsdl',
                         vim_obj.wsdl_url)
        self.assertEqual('https://[::1]:12345/sdk',
                         vim_obj.soap_url)

    def test_configure_with_wsdl_url_override(self):
        vim_obj = vim.Vim('https', 'www.example.com',
                          wsdl_url='https://test.com/sdk/vimService.wsdl')
        self.assertEqual('https://test.com/sdk/vimService.wsdl',
                         vim_obj.wsdl_url)
        self.assertEqual('https://www.example.com/sdk', vim_obj.soap_url)
