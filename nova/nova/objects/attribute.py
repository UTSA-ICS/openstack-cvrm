#    Copyright 2013 IBM Corp.
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
import traceback
from nova import db
from nova import exception
from nova.objects import base
from nova.objects import fields

class Attribute(base.NovaPersistentObject, base.NovaObject):
#class KeyPair(base.NovaPersistentObject, base.NovaObject):
    # Version 1.0: Initial version
    # Version 1.1: String attributes updated to support unicode
    VERSION = '1.1'
   
    fields = {
        'id': fields.IntegerField(),
        'name': fields.StringField(nullable=True),
        'project_id': fields.StringField(nullable=True),
   #     'user_id': fields.StringField(nullable=True),
    #    'fingerprint': fields.StringField(nullable=True),
     #   'public_key': fields.StringField(nullable=True),
        }
    def delete(self, context,id):
	#traceback.print_stack()
	print ("in delete ",id)
	db.attribute_delete(context, id) 
    def create(self, context):
        if self.obj_attr_is_set('id'):
           raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
	print context
        updates.pop('id', None)
        db_attribute = db.attribute_create(context, updates)
	print "in create/nova/object/attribute"
	return db_attribute
        #self._from_db_object(context, self, db_attribute)

    def list(self, context):
        #if self.obj_attr_is_set('id'):
         #  raise exception.ObjectActionError(action='create',
                                              #reason='already created')
        #updates = self.obj_get_changes()
        #updates.pop('id', None)
        #db_attribute = db.attribute_create(context, updates)
        #print "in create/nova/object/attribute"
        return db.attribute_list(context)    
    
    @staticmethod
    def _from_db_object(context, attribute, db_attribute):
        for id in attribute.id:
            attribute[id] = db_attribute[id]
        attribute._context = context
        attribute.obj_reset_changes()
        return attribute
    ''''
    @base.remotable_classmethod
    def get_by_name(cls, context, user_id, name):
        db_keypair = db.key_pair_get(context, user_id, name)
        return cls._from_db_object(context, cls(), db_keypair)

    @base.remotable_classmethod
    def destroy_by_name(cls, context, user_id, name):
        db.key_pair_destroy(context, user_id, name)

    @base.remotable
    def create(self, context):
        if self.obj_attr_is_set('id'):
            raise exception.ObjectActionError(action='create',
                                              reason='already created')
        updates = self.obj_get_changes()
        updates.pop('id', None)
        db_keypair = db.key_pair_create(context, updates)
        self._from_db_object(context, self, db_keypair)

    @base.remotable
    def destroy(self, context):
        db.key_pair_destroy(context, self.user_id, self.name)


class KeyPairList(base.ObjectListBase, base.NovaObject):
    # Version 1.0: Initial version
    #              KeyPair <= version 1.1
    VERSION = '1.0'

    fields = {
        'objects': fields.ListOfObjectsField('KeyPair'),
        }
    child_versions = {
        '1.0': '1.1',
        # NOTE(danms): KeyPair was at 1.1 before we added this
        }

    @base.remotable_classmethod
    def get_by_user(cls, context, user_id):
        db_keypairs = db.key_pair_get_all_by_user(context, user_id)
        return base.obj_make_list(context, KeyPairList(), KeyPair, db_keypairs)

    @base.remotable_classmethod
    def get_count_by_user(cls, context, user_id):
        return db.key_pair_count_by_user(context, user_id)
    '''
