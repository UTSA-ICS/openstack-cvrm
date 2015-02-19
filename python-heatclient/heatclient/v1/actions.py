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

from heatclient.openstack.common.apiclient import base
from heatclient.v1 import stacks

DEFAULT_PAGE_SIZE = 20


class Action(base.Resource):
    def __repr__(self):
        return "<Action %s>" % self._info

    def update(self, **fields):
        self.manager.update(self, **fields)

    def delete(self):
        return self.manager.delete(self)

    def data(self, **kwargs):
        return self.manager.data(self, **kwargs)


class ActionManager(stacks.StackChildManager):
    resource_class = Action

    def suspend(self, stack_id):
        """Suspend a stack."""
        body = {'suspend': None}
        resp, body = self.client.json_request('POST',
                                              '/stacks/%s/actions' % stack_id,
                                              data=body)

    def resume(self, stack_id):
        """Resume a stack."""
        body = {'resume': None}
        resp, body = self.client.json_request('POST',
                                              '/stacks/%s/actions' % stack_id,
                                              data=body)

    def cancel_update(self, stack_id):
        """Cancel running update of a stack."""
        body = {'cancel_update': None}
        resp, body = self.client.json_request('POST',
                                              '/stacks/%s/actions' % stack_id,
                                              data=body)

    def check(self, stack_id):
        """Check a stack."""
        body = {'check': None}
        resp, body = self.client.json_request('POST',
                                              '/stacks/%s/actions' % stack_id,
                                              data=body)
