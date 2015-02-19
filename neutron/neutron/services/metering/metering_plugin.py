# Copyright (C) 2013 eNovance SAS <licensing@enovance.com>
#
# Author: Sylvain Afchain <sylvain.afchain@enovance.com>
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

from neutron.api.rpc.agentnotifiers import metering_rpc_agent_api
from neutron.common import rpc as p_rpc
from neutron.common import topics
from neutron.db.metering import metering_db
from neutron.openstack.common import rpc


class MeteringCallbacks(metering_db.MeteringDbMixin):

    RPC_API_VERSION = '1.0'

    def __init__(self, plugin):
        self.plugin = plugin

    def create_rpc_dispatcher(self):
        return p_rpc.PluginRpcDispatcher([self])

    def get_sync_data_metering(self, context, **kwargs):
        return super(MeteringCallbacks, self).get_sync_data_metering(context)


class MeteringPlugin(metering_db.MeteringDbMixin):
    """Implementation of the Neutron Metering Service Plugin."""
    supported_extension_aliases = ["metering"]

    def __init__(self):
        super(MeteringPlugin, self).__init__()

        self.callbacks = MeteringCallbacks(self)

        self.conn = rpc.create_connection(new=True)
        self.conn.create_consumer(
            topics.METERING_PLUGIN,
            self.callbacks.create_rpc_dispatcher(),
            fanout=False)
        self.conn.consume_in_thread()

        self.meter_rpc = metering_rpc_agent_api.MeteringAgentNotifyAPI()

    def create_metering_label(self, context, metering_label):
        label = super(MeteringPlugin, self).create_metering_label(
            context, metering_label)

        data = self.get_sync_data_metering(context)
        self.meter_rpc.add_metering_label(context, data)

        return label

    def delete_metering_label(self, context, label_id):
        data = self.get_sync_data_metering(context, label_id)
        label = super(MeteringPlugin, self).delete_metering_label(
            context, label_id)

        self.meter_rpc.remove_metering_label(context, data)

        return label

    def create_metering_label_rule(self, context, metering_label_rule):
        rule = super(MeteringPlugin, self).create_metering_label_rule(
            context, metering_label_rule)

        data = self.get_sync_data_metering(context)
        self.meter_rpc.update_metering_label_rules(context, data)

        return rule

    def delete_metering_label_rule(self, context, rule_id):
        rule = super(MeteringPlugin, self).delete_metering_label_rule(
            context, rule_id)

        data = self.get_sync_data_metering(context)
        self.meter_rpc.update_metering_label_rules(context, data)

        return rule
