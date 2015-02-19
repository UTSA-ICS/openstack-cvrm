# Copyright 2012, VMware, Inc.
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

import fixtures
import mock
import testtools

from neutron.agent.linux import utils
from neutron.tests import base


class AgentUtilsExecuteTest(base.BaseTestCase):
    def setUp(self):
        super(AgentUtilsExecuteTest, self).setUp()
        self.root_helper = "echo"
        self.test_file = self.useFixture(
            fixtures.TempDir()).join("test_execute.tmp")
        open(self.test_file, 'w').close()
        self.mock_popen_p = mock.patch("subprocess.Popen.communicate")
        self.mock_popen = self.mock_popen_p.start()
        self.addCleanup(self.mock_popen_p.stop)

    def test_without_helper(self):
        expected = "%s\n" % self.test_file
        self.mock_popen.return_value = [expected, ""]
        result = utils.execute(["ls", self.test_file])
        self.assertEqual(result, expected)

    def test_with_helper(self):
        expected = "ls %s\n" % self.test_file
        self.mock_popen.return_value = [expected, ""]
        result = utils.execute(["ls", self.test_file],
                               self.root_helper)
        self.assertEqual(result, expected)

    def test_stderr_true(self):
        expected = "%s\n" % self.test_file
        self.mock_popen.return_value = [expected, ""]
        out = utils.execute(["ls", self.test_file], return_stderr=True)
        self.assertIsInstance(out, tuple)
        self.assertEqual(out, (expected, ""))

    def test_check_exit_code(self):
        self.mock_popen.return_value = ["", ""]
        stdout = utils.execute(["ls", self.test_file[:-1]],
                               check_exit_code=False)
        self.assertEqual(stdout, "")

    def test_execute_raises(self):
        self.mock_popen.side_effect = RuntimeError
        self.assertRaises(RuntimeError, utils.execute,
                          ["ls", self.test_file[:-1]])

    def test_process_input(self):
        expected = "%s\n" % self.test_file[:-1]
        self.mock_popen.return_value = [expected, ""]
        result = utils.execute(["cat"], process_input="%s\n" %
                               self.test_file[:-1])
        self.assertEqual(result, expected)

    def test_with_addl_env(self):
        expected = "%s\n" % self.test_file
        self.mock_popen.return_value = [expected, ""]
        result = utils.execute(["ls", self.test_file],
                               addl_env={'foo': 'bar'})
        self.assertEqual(result, expected)


class AgentUtilsGetInterfaceMAC(base.BaseTestCase):
    def test_get_interface_mac(self):
        expect_val = '01:02:03:04:05:06'
        with mock.patch('fcntl.ioctl') as ioctl:
            ioctl.return_value = ''.join(['\x00' * 18,
                                          '\x01\x02\x03\x04\x05\x06',
                                          '\x00' * 232])
            actual_val = utils.get_interface_mac('eth0')
        self.assertEqual(actual_val, expect_val)


class AgentUtilsReplaceFile(base.BaseTestCase):
    def test_replace_file(self):
        # make file to replace
        with mock.patch('tempfile.NamedTemporaryFile') as ntf:
            ntf.return_value.name = '/baz'
            with mock.patch('os.chmod') as chmod:
                with mock.patch('os.rename') as rename:
                    utils.replace_file('/foo', 'bar')

                    expected = [mock.call('w+', dir='/', delete=False),
                                mock.call().write('bar'),
                                mock.call().close()]

                    ntf.assert_has_calls(expected)
                    chmod.assert_called_once_with('/baz', 0o644)
                    rename.assert_called_once_with('/baz', '/foo')


class TestFindChildPids(base.BaseTestCase):

    def test_returns_empty_list_for_exit_code_1(self):
        with mock.patch.object(utils, 'execute',
                               side_effect=RuntimeError('Exit code: 1')):
            self.assertEqual(utils.find_child_pids(-1), [])

    def test_returns_empty_list_for_no_output(self):
        with mock.patch.object(utils, 'execute', return_value=''):
            self.assertEqual(utils.find_child_pids(-1), [])

    def test_returns_list_of_child_process_ids_for_good_ouput(self):
        with mock.patch.object(utils, 'execute', return_value=' 123 \n 185\n'):
            self.assertEqual(utils.find_child_pids(-1), ['123', '185'])

    def test_raises_unknown_exception(self):
        with testtools.ExpectedException(RuntimeError):
            with mock.patch.object(utils, 'execute',
                                   side_effect=RuntimeError()):
                utils.find_child_pids(-1)
