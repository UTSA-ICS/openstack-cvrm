# Copyright (c) 2013 NEC Corporation
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
#
# @author: Akihiro Motoki, NEC Corporation


"""setup_mock_calls and verify_mock_calls are convenient methods
to setup a sequence of mock calls.

expected_calls_and_values is a list of (expected_call, return_value):

        expected_calls_and_values = [
            (mock.call(["ovs-vsctl", self.TO, '--', "--may-exist", "add-port",
                        self.BR_NAME, pname], root_helper=self.root_helper),
             None),
            (mock.call(["ovs-vsctl", self.TO, "set", "Interface",
                        pname, "type=gre"], root_helper=self.root_helper),
             None),
            ....
        ]

* expected_call should be mock.call(expected_arg, ....)
* return_value is passed to side_effect of a mocked call.
  A return value or an exception can be specified.
"""


def setup_mock_calls(mocked_call, expected_calls_and_values):
    return_values = [call[1] for call in expected_calls_and_values]
    mocked_call.side_effect = return_values


def verify_mock_calls(mocked_call, expected_calls_and_values):
    expected_calls = [call[0] for call in expected_calls_and_values]
    mocked_call.assert_has_calls(expected_calls)
