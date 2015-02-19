#    Copyright 2013 Rackspace Hosting.
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


from nova.objects import base
from nova.objects import fields
from nova import quota


def ids_from_instance(context, instance):
    if (context.is_admin and
            context.project_id != instance['project_id']):
        project_id = instance['project_id']
    else:
        project_id = context.project_id
    if context.user_id != instance['user_id']:
        user_id = instance['user_id']
    else:
        user_id = context.user_id
    return project_id, user_id


# TODO(lyj): This method needs to be cleaned up once the
# ids_from_instance helper method is renamed or some common
# method is added for objects.quotas.
def ids_from_security_group(context, security_group):
    return ids_from_instance(context, security_group)


class Quotas(base.NovaObject):
    fields = {
        'reservations': fields.ListOfStringsField(nullable=True),
        'project_id': fields.StringField(nullable=True),
        'user_id': fields.StringField(nullable=True),
    }

    def __init__(self):
        super(Quotas, self).__init__()
        # Set up defaults.
        self.reservations = []
        self.project_id = None
        self.user_id = None
        self.obj_reset_changes()

    @classmethod
    def from_reservations(cls, context, reservations, instance=None):
        """Transitional for compatibility."""
        if instance is None:
            project_id = None
            user_id = None
        else:
            project_id, user_id = ids_from_instance(context, instance)
        quotas = cls()
        quotas._context = context
        quotas.reservations = reservations
        quotas.project_id = project_id
        quotas.user_id = user_id
        quotas.obj_reset_changes()
        return quotas

    @base.remotable
    def reserve(self, context, expire=None, project_id=None, user_id=None,
                **deltas):
        reservations = quota.QUOTAS.reserve(context, expire=expire,
                                            project_id=project_id,
                                            user_id=user_id,
                                            **deltas)
        self.reservations = reservations
        self.project_id = project_id
        self.user_id = user_id
        self.obj_reset_changes()

    @base.remotable
    def commit(self, context=None):
        if not self.reservations:
            return
        if context is None:
            context = self._context
        quota.QUOTAS.commit(context, self.reservations,
                            project_id=self.project_id,
                            user_id=self.user_id)
        self.reservations = None
        self.obj_reset_changes()

    @base.remotable
    def rollback(self, context=None):
        """Rollback quotas."""
        if not self.reservations:
            return
        if context is None:
            context = self._context
        quota.QUOTAS.rollback(context, self.reservations,
                              project_id=self.project_id,
                              user_id=self.user_id)
        self.reservations = None
        self.obj_reset_changes()


class QuotasNoOp(Quotas):
    def reserve(context, expire=None, project_id=None, user_id=None,
                **deltas):
        pass

    def commit(self, context=None):
        pass

    def rollback(self, context=None):
        pass
