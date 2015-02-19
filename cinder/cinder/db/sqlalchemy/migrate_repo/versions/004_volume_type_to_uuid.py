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

import uuid

from cinder.openstack.common import log as logging
from migrate import ForeignKeyConstraint
from sqlalchemy import Integer, MetaData, String, Table

LOG = logging.getLogger(__name__)


def upgrade(migrate_engine):
    """Convert volume_type_id to UUID."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    volume_types = Table('volume_types', meta, autoload=True)
    extra_specs = Table('volume_type_extra_specs', meta, autoload=True)

    fkey_remove_list = [volumes.c.volume_type_id,
                        volume_types.c.id,
                        extra_specs.c.volume_type_id]

    for column in fkey_remove_list:
        fkeys = list(column.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            fkey = ForeignKeyConstraint(columns=[column],
                                        refcolumns=[volume_types.c.id],
                                        name=fkey_name)

            try:
                fkey.drop()
            except Exception:
                if migrate_engine.url.get_dialect().name.startswith('sqlite'):
                    pass
                else:
                    raise

    volumes.c.volume_type_id.alter(String(36))
    volume_types.c.id.alter(String(36))
    extra_specs.c.volume_type_id.alter(String(36))

    vtype_list = list(volume_types.select().execute())
    for t in vtype_list:
        new_id = str(uuid.uuid4())

        volumes.update().\
            where(volumes.c.volume_type_id == t['id']).\
            values(volume_type_id=new_id).execute()

        extra_specs.update().\
            where(extra_specs.c.volume_type_id == t['id']).\
            values(volume_type_id=new_id).execute()

        volume_types.update().\
            where(volume_types.c.id == t['id']).\
            values(id=new_id).execute()

    for column in fkey_remove_list:
        fkeys = list(column.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            fkey = ForeignKeyConstraint(columns=[column],
                                        refcolumns=[volume_types.c.id],
                                        name=fkey_name)
            try:
                fkey.create()
                LOG.info('Created foreign key %s' % fkey_name)
            except Exception:
                if migrate_engine.url.get_dialect().name.startswith('sqlite'):
                    pass
                else:
                    raise


def downgrade(migrate_engine):
    """Convert volume_type from UUID back to int."""
    meta = MetaData()
    meta.bind = migrate_engine

    volumes = Table('volumes', meta, autoload=True)
    volume_types = Table('volume_types', meta, autoload=True)
    extra_specs = Table('volume_type_extra_specs', meta, autoload=True)

    fkey_remove_list = [volumes.c.volume_type_id,
                        volume_types.c.id,
                        extra_specs.c.volume_type_id]

    for column in fkey_remove_list:
        fkeys = list(column.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            fkey = ForeignKeyConstraint(columns=[column],
                                        refcolumns=[volume_types.c.id],
                                        name=fkey_name)

            try:
                fkey.drop()
            except Exception:
                if migrate_engine.url.get_dialect().name.startswith('sqlite'):
                    pass
                else:
                    raise

    vtype_list = list(volume_types.select().execute())
    new_id = 1

    for t in vtype_list:
        volumes.update().\
            where(volumes.c.volume_type_id == t['id']).\
            values(volume_type_id=new_id).execute()

        extra_specs.update().\
            where(extra_specs.c.volume_type_id == t['id']).\
            values(volume_type_id=new_id).execute()

        volume_types.update().\
            where(volume_types.c.id == t['id']).\
            values(id=new_id).execute()

        new_id += 1

    volumes.c.volume_type_id.alter(Integer)
    volume_types.c.id.alter(Integer)
    extra_specs.c.volume_type_id.alter(Integer)

    for column in fkey_remove_list:
        fkeys = list(column.foreign_keys)
        if fkeys:
            fkey_name = fkeys[0].constraint.name
            fkey = ForeignKeyConstraint(columns=[column],
                                        refcolumns=[volume_types.c.id],
                                        name=fkey_name)
            try:
                fkey.create()
                LOG.info('Created foreign key %s' % fkey_name)
            except Exception:
                if migrate_engine.url.get_dialect().name.startswith('sqlite'):
                    pass
                else:
                    raise
