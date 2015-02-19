# Copyright 2013 OpenStack Foundation
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

from nova import test
from nova.virt.vmwareapi import error_util
from nova.virt.vmwareapi import fake


class ExpectedMethodFault:
    pass


class ErrorUtilTestCase(test.NoDBTestCase):
    def setUp(self):
        super(ErrorUtilTestCase, self).setUp()

    def test_fault_checker_empty_response(self):
        # assertRaises as a Context Manager would have been a good choice to
        # perform additional checks on the exception raised, instead of
        # try/catch block in the below tests, but it's available
        # only from  Py 2.7.
        exp_fault_list = [error_util.NOT_AUTHENTICATED]
        try:
            error_util.FaultCheckers.retrievepropertiesex_fault_checker(None)
        except error_util.VimFaultException as e:
            self.assertEqual(exp_fault_list, e.fault_list)
        else:
            self.fail("VimFaultException was not raised.")

    def test_fault_checker_missing_props(self):
        fake_objects = fake.FakeRetrieveResult()
        ml = [fake.MissingProperty(method_fault=ExpectedMethodFault())]
        fake_objects.add_object(fake.ObjectContent(None, missing_list=ml))

        exp_fault_list = ['ExpectedMethodFault']
        try:
            error_util.FaultCheckers.retrievepropertiesex_fault_checker(
                fake_objects)
        except error_util.VimFaultException as e:
            self.assertEqual(exp_fault_list, e.fault_list)
        else:
            self.fail("VimFaultException was not raised.")

    def test_fault_checker_no_missing_props(self):
        fake_objects = fake.FakeRetrieveResult()
        fake_objects.add_object(fake.ObjectContent(None))
        self.assertIsNone(
            error_util.FaultCheckers.retrievepropertiesex_fault_checker(
                fake_objects))

    def test_exception_summary_exception_as_list(self):
        # assert that if a list is fed to the VimException object
        # that it will error.
        self.assertRaises(ValueError,
                          error_util.VimException,
                          [], ValueError('foo'))

    def test_exception_summary_string(self):
        e = error_util.VimException("string", ValueError("foo"))
        string = str(e)
        self.assertEqual("string: foo", string)

    def test_vim_fault_exception_string(self):
        self.assertRaises(ValueError,
                          error_util.VimFaultException,
                          "bad", ValueError("argument"))

    def test_vim_fault_exception(self):
        vfe = error_util.VimFaultException([ValueError("example")], "cause")
        string = str(vfe)
        self.assertEqual("cause", string)
