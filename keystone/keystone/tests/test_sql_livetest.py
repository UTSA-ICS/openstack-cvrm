# Copyright 2013 Red Hat, Inc
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

from keystone import config
from keystone import tests
from keystone.tests import test_sql_migrate_extensions
from keystone.tests import test_sql_upgrade


CONF = config.CONF


class PostgresqlMigrateTests(test_sql_upgrade.SqlUpgradeTests):
    def setUp(self):
        self.skip_if_env_not_set('ENABLE_LIVE_POSTGRES_TEST')
        super(PostgresqlMigrateTests, self).setUp()

    def config_files(self):
        files = (test_sql_upgrade.SqlUpgradeTests.
                 _config_file_list[:])
        files.append(tests.dirs.tests_conf("backend_postgresql.conf"))
        return files


class MysqlMigrateTests(test_sql_upgrade.SqlUpgradeTests):
    def setUp(self):
        self.skip_if_env_not_set('ENABLE_LIVE_MYSQL_TEST')
        super(MysqlMigrateTests, self).setUp()

    def config_files(self):
        files = (test_sql_upgrade.SqlUpgradeTests.
                 _config_file_list[:])
        files.append(tests.dirs.tests_conf("backend_mysql.conf"))
        return files


class PostgresqlRevokeExtensionsTests(
        test_sql_migrate_extensions.RevokeExtension):
    def setUp(self):
        self.skip_if_env_not_set('ENABLE_LIVE_POSTGRES_TEST')
        super(PostgresqlRevokeExtensionsTests, self).setUp()

    def config_files(self):
        files = (test_sql_upgrade.SqlUpgradeTests.
                 _config_file_list[:])
        files.append(tests.dirs.tests_conf("backend_postgresql.conf"))
        return files


class MysqlRevokeExtensionsTests(test_sql_migrate_extensions.RevokeExtension):
    def setUp(self):
        self.skip_if_env_not_set('ENABLE_LIVE_MYSQL_TEST')
        super(MysqlRevokeExtensionsTests, self).setUp()

    def config_files(self):
        files = (test_sql_upgrade.SqlUpgradeTests.
                 _config_file_list[:])
        files.append(tests.dirs.tests_conf("backend_mysql.conf"))
        return files


class Db2MigrateTests(test_sql_upgrade.SqlUpgradeTests):
    def setUp(self):
        self.skip_if_env_not_set('ENABLE_LIVE_DB2_TEST')
        super(Db2MigrateTests, self).setUp()

    def config_files(self):
        files = (test_sql_upgrade.SqlUpgradeTests.
                 _config_file_list[:])
        files.append(tests.dirs.tests_conf("backend_db2.conf"))
        return files
