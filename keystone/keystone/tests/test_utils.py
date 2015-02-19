# Copyright 2012 OpenStack Foundation
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

# Copyright 2012 Justin Santa Barbara
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

import datetime
import functools
import os
import time

from keystone.common import utils
from keystone import service
from keystone import tests


TZ = None


def timezone(func):
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        tz_original = os.environ.get('TZ')
        try:
            if TZ:
                os.environ['TZ'] = TZ
                time.tzset()
            return func(*args, **kwargs)
        finally:
            if TZ:
                if tz_original:
                    os.environ['TZ'] = tz_original
                else:
                    if 'TZ' in os.environ:
                        del os.environ['TZ']
                time.tzset()
    return wrapper


class UtilsTestCase(tests.TestCase):
    OPTIONAL = object()

    def test_hash(self):
        password = 'right'
        wrong = 'wrongwrong'  # Two wrongs don't make a right
        hashed = utils.hash_password(password)
        self.assertTrue(utils.check_password(password, hashed))
        self.assertFalse(utils.check_password(wrong, hashed))

    def test_hash_long_password(self):
        bigboy = '0' * 9999999
        hashed = utils.hash_password(bigboy)
        self.assertTrue(utils.check_password(bigboy, hashed))

    def _create_test_user(self, password=OPTIONAL):
        user = {"name": "hthtest"}
        if password is not self.OPTIONAL:
            user['password'] = password

        return user

    def test_hash_user_password_without_password(self):
        user = self._create_test_user()
        hashed = utils.hash_user_password(user)
        self.assertEqual(user, hashed)

    def test_hash_user_password_with_null_password(self):
        user = self._create_test_user(password=None)
        hashed = utils.hash_user_password(user)
        self.assertEqual(user, hashed)

    def test_hash_user_password_with_empty_password(self):
        password = ''
        user = self._create_test_user(password=password)
        user_hashed = utils.hash_user_password(user)
        password_hashed = user_hashed['password']
        self.assertTrue(utils.check_password(password, password_hashed))

    def test_hash_ldap_user_password_without_password(self):
        user = self._create_test_user()
        hashed = utils.hash_ldap_user_password(user)
        self.assertEqual(user, hashed)

    def test_hash_ldap_user_password_with_null_password(self):
        user = self._create_test_user(password=None)
        hashed = utils.hash_ldap_user_password(user)
        self.assertEqual(user, hashed)

    def test_hash_ldap_user_password_with_empty_password(self):
        password = ''
        user = self._create_test_user(password=password)
        user_hashed = utils.hash_ldap_user_password(user)
        password_hashed = user_hashed['password']
        self.assertTrue(utils.ldap_check_password(password, password_hashed))

    def test_hash_edge_cases(self):
        hashed = utils.hash_password('secret')
        self.assertFalse(utils.check_password('', hashed))
        self.assertFalse(utils.check_password(None, hashed))

    def test_hash_unicode(self):
        password = u'Comment \xe7a va'
        wrong = 'Comment ?a va'
        hashed = utils.hash_password(password)
        self.assertTrue(utils.check_password(password, hashed))
        self.assertFalse(utils.check_password(wrong, hashed))

    def test_auth_str_equal(self):
        self.assertTrue(utils.auth_str_equal('abc123', 'abc123'))
        self.assertFalse(utils.auth_str_equal('a', 'aaaaa'))
        self.assertFalse(utils.auth_str_equal('aaaaa', 'a'))
        self.assertFalse(utils.auth_str_equal('ABC123', 'abc123'))

    def test_unixtime(self):
        global TZ

        @timezone
        def _test_unixtime():
            epoch = utils.unixtime(dt)
            self.assertEqual(epoch, epoch_ans, "TZ=%s" % TZ)

        dt = datetime.datetime(1970, 1, 2, 3, 4, 56, 0)
        epoch_ans = 56 + 4 * 60 + 3 * 3600 + 86400
        for d in ['+0', '-11', '-8', '-5', '+5', '+8', '+14']:
            TZ = 'UTC' + d
            _test_unixtime()


class ServiceHelperTests(tests.TestCase):

    @service.fail_gracefully
    def _do_test(self):
        raise Exception("Test Exc")

    def test_fail_gracefully(self):
        self.assertRaises(tests.UnexpectedExit, self._do_test)


class LimitingReaderTests(tests.TestCase):

    def test_read_default_value(self):

        class FakeData(object):
            def read(self, *args, **kwargs):
                self.read_args = args
                self.read_kwargs = kwargs
                return 'helloworld'

        data = FakeData()
        utils.LimitingReader(data, 100)

        self.assertEqual(data.read(), 'helloworld')
        self.assertEqual(len(data.read_args), 0)
        self.assertEqual(len(data.read_kwargs), 0)

        self.assertEqual(data.read(10), 'helloworld')
        self.assertEqual(len(data.read_args), 1)
        self.assertEqual(len(data.read_kwargs), 0)
        self.assertEqual(data.read_args[0], 10)
