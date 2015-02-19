# Copyright 2010 United States Government as represented by the
# Administrator of the National Aeronautics and Space Administration.
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


import os

from migrate import exceptions as versioning_exceptions
from migrate.versioning import api as versioning_api
from migrate.versioning.repository import Repository
import sqlalchemy

from cinder.db.sqlalchemy.api import get_engine
from cinder import exception

INIT_VERSION = 000
_REPOSITORY = None


def _ensure_reservations_index(migrate_engine):
    meta = sqlalchemy.MetaData()
    meta.bind = migrate_engine

    reservations = sqlalchemy.Table('reservations', meta, autoload=True)
    members = sorted(['deleted', 'expire'])
    for idx in reservations.indexes:
        if sorted(idx.columns.keys()) == members:
            return

    # Based on expire_reservations query
    # from: cinder/db/sqlalchemy/api.py
    index = sqlalchemy.Index('reservations_deleted_expire_idx',
                             reservations.c.deleted, reservations.c.expire)

    index.create(migrate_engine)


def db_sync(version=None):
    if version is not None:
        try:
            version = int(version)
        except ValueError:
            raise exception.Error(_("version should be an integer"))

    current_version = db_version()
    repository = _find_migrate_repo()
    migrate_engine = get_engine()
    if version is None or version > current_version:
        result = versioning_api.upgrade(migrate_engine, repository, version)
    else:
        result = versioning_api.downgrade(migrate_engine, repository,
                                          version)
    _ensure_reservations_index(migrate_engine)
    return result


def db_version():
    repository = _find_migrate_repo()
    try:
        return versioning_api.db_version(get_engine(), repository)
    except versioning_exceptions.DatabaseNotControlledError:
        # If we aren't version controlled we may already have the database
        # in the state from before we started version control, check for that
        # and set up version_control appropriately
        meta = sqlalchemy.MetaData()
        engine = get_engine()
        meta.reflect(bind=engine)
        tables = meta.tables
        if len(tables) == 0:
            db_version_control(INIT_VERSION)
            return versioning_api.db_version(get_engine(), repository)
        else:
            raise exception.Error(_("Upgrade DB using Essex release first."))


def db_initial_version():
    return INIT_VERSION


def db_version_control(version=None):
    repository = _find_migrate_repo()
    versioning_api.version_control(get_engine(), repository, version)
    return version


def _find_migrate_repo():
    """Get the path for the migrate repository."""
    global _REPOSITORY
    path = os.path.join(os.path.abspath(os.path.dirname(__file__)),
                        'migrate_repo')
    assert os.path.exists(path)
    if _REPOSITORY is None:
        _REPOSITORY = Repository(path)
    return _REPOSITORY
