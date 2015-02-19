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

"""Handles database requests from other nova services."""

from oslo import messaging
import six

from nova.api.ec2 import ec2utils
from nova import block_device
from nova.cells import rpcapi as cells_rpcapi
from nova.compute import api as compute_api
from nova.compute import rpcapi as compute_rpcapi
from nova.compute import task_states
from nova.compute import utils as compute_utils
from nova.compute import vm_states
from nova.conductor.tasks import live_migrate
from nova.db import base
from nova import exception
from nova.image import glance
from nova import manager
from nova import network
from nova.network.security_group import openstack_driver
from nova import notifications
from nova.objects import base as nova_object
from nova.objects import instance as instance_obj
from nova.objects import migration as migration_obj
from nova.objects import quotas as quotas_obj
from nova.openstack.common import excutils
from nova.openstack.common.gettextutils import _
from nova.openstack.common import jsonutils
from nova.openstack.common import log as logging
from nova.openstack.common import timeutils
from nova import quota
from nova.scheduler import rpcapi as scheduler_rpcapi
from nova.scheduler import utils as scheduler_utils

LOG = logging.getLogger(__name__)

# Instead of having a huge list of arguments to instance_update(), we just
# accept a dict of fields to update and use this whitelist to validate it.
allowed_updates = ['task_state', 'vm_state', 'expected_task_state',
                   'power_state', 'access_ip_v4', 'access_ip_v6',
                   'launched_at', 'terminated_at', 'host', 'node',
                   'memory_mb', 'vcpus', 'root_gb', 'ephemeral_gb',
                   'instance_type_id', 'root_device_name', 'launched_on',
                   'progress', 'vm_mode', 'default_ephemeral_device',
                   'default_swap_device', 'root_device_name',
                   'system_metadata', 'updated_at'
                   ]

# Fields that we want to convert back into a datetime object.
datetime_fields = ['launched_at', 'terminated_at', 'updated_at']


class ConductorManager(manager.Manager):
    """Mission: Conduct things.

    The methods in the base API for nova-conductor are various proxy operations
    performed on behalf of the nova-compute service running on compute nodes.
    Compute nodes are not allowed to directly access the database, so this set
    of methods allows them to get specific work done without locally accessing
    the database.

    The nova-conductor service also exposes an API in the 'compute_task'
    namespace.  See the ComputeTaskManager class for details.
    """

    target = messaging.Target(version='1.64')

    def __init__(self, *args, **kwargs):
        super(ConductorManager, self).__init__(service_name='conductor',
                                               *args, **kwargs)
        self.security_group_api = (
            openstack_driver.get_openstack_security_group_driver())
        self._network_api = None
        self._compute_api = None
        self.compute_task_mgr = ComputeTaskManager()
        self.cells_rpcapi = cells_rpcapi.CellsAPI()
        self.additional_endpoints.append(self.compute_task_mgr)
        self.additional_endpoints.append(_ConductorManagerV2Proxy(self))

    @property
    def network_api(self):
        # NOTE(danms): We need to instantiate our network_api on first use
        # to avoid the circular dependency that exists between our init
        # and network_api's
        if self._network_api is None:
            self._network_api = network.API()
        return self._network_api

    @property
    def compute_api(self):
        if self._compute_api is None:
            self._compute_api = compute_api.API()
        return self._compute_api

    def ping(self, context, arg):
        # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
        # now a part of the base rpc API.
        return jsonutils.to_primitive({'service': 'conductor', 'arg': arg})

    @messaging.expected_exceptions(KeyError, ValueError,
                                   exception.InvalidUUID,
                                   exception.InstanceNotFound,
                                   exception.UnexpectedTaskStateError)
    def instance_update(self, context, instance_uuid,
                        updates, service=None):
        for key, value in updates.iteritems():
            if key not in allowed_updates:
                LOG.error(_("Instance update attempted for "
                            "'%(key)s' on %(instance_uuid)s"),
                          {'key': key, 'instance_uuid': instance_uuid})
                raise KeyError("unexpected update keyword '%s'" % key)
            if key in datetime_fields and isinstance(value, six.string_types):
                updates[key] = timeutils.parse_strtime(value)

        old_ref, instance_ref = self.db.instance_update_and_get_original(
            context, instance_uuid, updates)
        notifications.send_update(context, old_ref, instance_ref, service)
        return jsonutils.to_primitive(instance_ref)

    # NOTE(russellb): This method is now deprecated and can be removed in
    # version 2.0 of the RPC API
    @messaging.expected_exceptions(exception.InstanceNotFound)
    def instance_get(self, context, instance_id):
        return jsonutils.to_primitive(
            self.db.instance_get(context, instance_id))

    @messaging.expected_exceptions(exception.InstanceNotFound)
    def instance_get_by_uuid(self, context, instance_uuid,
                             columns_to_join=None):
        return jsonutils.to_primitive(
            self.db.instance_get_by_uuid(context, instance_uuid,
                columns_to_join))

    # NOTE(hanlind): This method can be removed in v2.0 of the RPC API.
    def instance_get_all(self, context):
        return jsonutils.to_primitive(self.db.instance_get_all(context))

    def instance_get_all_by_host(self, context, host, node=None,
                                 columns_to_join=None):
        if node is not None:
            result = self.db.instance_get_all_by_host_and_node(
                context.elevated(), host, node)
        else:
            result = self.db.instance_get_all_by_host(context.elevated(), host,
                                                      columns_to_join)
        return jsonutils.to_primitive(result)

    # NOTE(comstud): This method is now deprecated and can be removed in
    # version v2.0 of the RPC API
    @messaging.expected_exceptions(exception.MigrationNotFound)
    def migration_get(self, context, migration_id):
        migration_ref = self.db.migration_get(context.elevated(),
                                              migration_id)
        return jsonutils.to_primitive(migration_ref)

    # NOTE(comstud): This method is now deprecated and can be removed in
    # version v2.0 of the RPC API
    def migration_get_unconfirmed_by_dest_compute(self, context,
                                                  confirm_window,
                                                  dest_compute):
        migrations = self.db.migration_get_unconfirmed_by_dest_compute(
            context, confirm_window, dest_compute)
        return jsonutils.to_primitive(migrations)

    def migration_get_in_progress_by_host_and_node(self, context,
                                                   host, node):
        migrations = self.db.migration_get_in_progress_by_host_and_node(
            context, host, node)
        return jsonutils.to_primitive(migrations)

    # NOTE(comstud): This method can be removed in v2.0 of the RPC API.
    def migration_create(self, context, instance, values):
        values.update({'instance_uuid': instance['uuid'],
                       'source_compute': instance['host'],
                       'source_node': instance['node']})
        migration_ref = self.db.migration_create(context.elevated(), values)
        return jsonutils.to_primitive(migration_ref)

    # NOTE(russellb): This method is now deprecated and can be removed in
    # version 2.0 of the RPC API
    @messaging.expected_exceptions(exception.MigrationNotFound)
    def migration_update(self, context, migration, status):
        migration_ref = self.db.migration_update(context.elevated(),
                                                 migration['id'],
                                                 {'status': status})
        return jsonutils.to_primitive(migration_ref)

    @messaging.expected_exceptions(exception.AggregateHostExists)
    def aggregate_host_add(self, context, aggregate, host):
        host_ref = self.db.aggregate_host_add(context.elevated(),
                aggregate['id'], host)

        return jsonutils.to_primitive(host_ref)

    @messaging.expected_exceptions(exception.AggregateHostNotFound)
    def aggregate_host_delete(self, context, aggregate, host):
        self.db.aggregate_host_delete(context.elevated(),
                aggregate['id'], host)

    # NOTE(russellb): This method is now deprecated and can be removed in
    # version 2.0 of the RPC API
    @messaging.expected_exceptions(exception.AggregateNotFound)
    def aggregate_get(self, context, aggregate_id):
        aggregate = self.db.aggregate_get(context.elevated(), aggregate_id)
        return jsonutils.to_primitive(aggregate)

    # NOTE(russellb): This method is now deprecated and can be removed in
    # version 2.0 of the RPC API
    def aggregate_get_by_host(self, context, host, key=None):
        aggregates = self.db.aggregate_get_by_host(context.elevated(),
                                                   host, key)
        return jsonutils.to_primitive(aggregates)

    # NOTE(danms): This method is now deprecated and can be removed in
    # version 2.0 of the RPC API
    def aggregate_metadata_add(self, context, aggregate, metadata,
                               set_delete=False):
        new_metadata = self.db.aggregate_metadata_add(context.elevated(),
                                                      aggregate['id'],
                                                      metadata, set_delete)
        return jsonutils.to_primitive(new_metadata)

    # NOTE(danms): This method is now deprecated and can be removed in
    # version 2.0 of the RPC API
    @messaging.expected_exceptions(exception.AggregateMetadataNotFound)
    def aggregate_metadata_delete(self, context, aggregate, key):
        self.db.aggregate_metadata_delete(context.elevated(),
                                          aggregate['id'], key)

    def aggregate_metadata_get_by_host(self, context, host,
                                       key='availability_zone'):
        result = self.db.aggregate_metadata_get_by_host(context, host, key)
        return jsonutils.to_primitive(result)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in=None, bw_out=None,
                        last_ctr_in=None, last_ctr_out=None,
                        last_refreshed=None,
                        update_cells=True):
        if [bw_in, bw_out, last_ctr_in, last_ctr_out].count(None) != 4:
            self.db.bw_usage_update(context, uuid, mac, start_period,
                                    bw_in, bw_out, last_ctr_in, last_ctr_out,
                                    last_refreshed,
                                    update_cells=update_cells)
        usage = self.db.bw_usage_get(context, uuid, start_period, mac)
        return jsonutils.to_primitive(usage)

    # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
    # deprecated in favor of the method in the base API.
    def get_backdoor_port(self, context):
        return self.backdoor_port

    # NOTE(danms): This method can be removed in version 2.0 of this API.
    def security_group_get_by_instance(self, context, instance):
        group = self.db.security_group_get_by_instance(context,
                                                       instance['uuid'])
        return jsonutils.to_primitive(group)

    # NOTE(danms): This method can be removed in version 2.0 of this API.
    def security_group_rule_get_by_security_group(self, context, secgroup):
        rules = self.db.security_group_rule_get_by_security_group(
            context, secgroup['id'])
        return jsonutils.to_primitive(rules, max_depth=4)

    def provider_fw_rule_get_all(self, context):
        rules = self.db.provider_fw_rule_get_all(context)
        return jsonutils.to_primitive(rules)

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        info = self.db.agent_build_get_by_triple(context, hypervisor, os,
                                                 architecture)
        return jsonutils.to_primitive(info)

    def block_device_mapping_update_or_create(self, context, values,
                                              create=None):
        if create is None:
            bdm = self.db.block_device_mapping_update_or_create(context,
                                                                values)
        elif create is True:
            bdm = self.db.block_device_mapping_create(context, values)
        else:
            bdm = self.db.block_device_mapping_update(context,
                                                      values['id'],
                                                      values)
        # NOTE:comstud): 'bdm' is always in the new format, so we
        # account for this in cells/messaging.py
        self.cells_rpcapi.bdm_update_or_create_at_top(context, bdm,
                                                      create=create)

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy=True):
        bdms = self.db.block_device_mapping_get_all_by_instance(
            context, instance['uuid'])
        if legacy:
            bdms = block_device.legacy_mapping(bdms)
        return jsonutils.to_primitive(bdms)

    # NOTE(russellb) This method can be removed in 2.0 of this API.  It is
    # deprecated in favor of the method in the base API.
    def block_device_mapping_destroy(self, context, bdms=None,
                                     instance=None, volume_id=None,
                                     device_name=None):
        if bdms is not None:
            for bdm in bdms:
                self.db.block_device_mapping_destroy(context, bdm['id'])
                # NOTE(comstud): bdm['id'] will be different in API cell,
                # so we must try to destroy by device_name or volume_id.
                # We need an instance_uuid in order to do this properly,
                # too.
                # I hope to clean a lot of this up in the object
                # implementation.
                instance_uuid = (bdm['instance_uuid'] or
                                    (instance and instance['uuid']))
                if not instance_uuid:
                    continue
                # Better to be safe than sorry.  device_name is not
                # NULLable, however it could be an empty string.
                if bdm['device_name']:
                    self.cells_rpcapi.bdm_destroy_at_top(
                            context, instance_uuid,
                            device_name=bdm['device_name'])
                elif bdm['volume_id']:
                    self.cells_rpcapi.bdm_destroy_at_top(
                            context, instance_uuid,
                            volume_id=bdm['volume_id'])
        elif instance is not None and volume_id is not None:
            self.db.block_device_mapping_destroy_by_instance_and_volume(
                context, instance['uuid'], volume_id)
            self.cells_rpcapi.bdm_destroy_at_top(
                context, instance['uuid'], volume_id=volume_id)
        elif instance is not None and device_name is not None:
            self.db.block_device_mapping_destroy_by_instance_and_device(
                context, instance['uuid'], device_name)
            self.cells_rpcapi.bdm_destroy_at_top(
                context, instance['uuid'], device_name=device_name)
        else:
            # NOTE(danms): This shouldn't happen
            raise exception.Invalid(_("Invalid block_device_mapping_destroy"
                                      " invocation"))

    def instance_get_all_by_filters(self, context, filters, sort_key,
                                    sort_dir, columns_to_join=None,
                                    use_slave=False):
        result = self.db.instance_get_all_by_filters(
            context, filters, sort_key, sort_dir,
            columns_to_join=columns_to_join, use_slave=use_slave)
        return jsonutils.to_primitive(result)

    # NOTE(hanlind): This method can be removed in v2.0 of the RPC API.
    def instance_get_all_hung_in_rebooting(self, context, timeout):
        result = self.db.instance_get_all_hung_in_rebooting(context, timeout)
        return jsonutils.to_primitive(result)

    def instance_get_active_by_window(self, context, begin, end=None,
                                      project_id=None, host=None):
        # Unused, but cannot remove until major RPC version bump
        result = self.db.instance_get_active_by_window(context, begin, end,
                                                       project_id, host)
        return jsonutils.to_primitive(result)

    def instance_get_active_by_window_joined(self, context, begin, end=None,
                                             project_id=None, host=None):
        result = self.db.instance_get_active_by_window_joined(
            context, begin, end, project_id, host)
        return jsonutils.to_primitive(result)

    def instance_destroy(self, context, instance):
        result = self.db.instance_destroy(context, instance['uuid'])
        return jsonutils.to_primitive(result)

    def instance_info_cache_delete(self, context, instance):
        self.db.instance_info_cache_delete(context, instance['uuid'])

    # NOTE(hanlind): This method is now deprecated and can be removed in
    # version v2.0 of the RPC API.
    def instance_info_cache_update(self, context, instance, values):
        self.db.instance_info_cache_update(context, instance['uuid'],
                                           values)

    # NOTE(danms): This method is now deprecated and can be removed in
    # version v2.0 of the RPC API.
    def instance_type_get(self, context, instance_type_id):
        result = self.db.flavor_get(context, instance_type_id)
        return jsonutils.to_primitive(result)

    def instance_fault_create(self, context, values):
        result = self.db.instance_fault_create(context, values)
        return jsonutils.to_primitive(result)

    # NOTE(kerrin): This method can be removed in v2.0 of the RPC API.
    def vol_get_usage_by_time(self, context, start_time):
        result = self.db.vol_get_usage_by_time(context, start_time)
        return jsonutils.to_primitive(result)

    # NOTE(kerrin): The last_refreshed argument is unused by this method
    # and can be removed in v2.0 of the RPC API.
    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed=None,
                         update_totals=False):
        vol_usage = self.db.vol_usage_update(context, vol_id,
                                             rd_req, rd_bytes,
                                             wr_req, wr_bytes,
                                             instance['uuid'],
                                             instance['project_id'],
                                             instance['user_id'],
                                             instance['availability_zone'],
                                             update_totals)

        # We have just updated the database, so send the notification now
        self.notifier.info(context, 'volume.usage',
                           compute_utils.usage_volume_info(vol_usage))

    @messaging.expected_exceptions(exception.ComputeHostNotFound,
                                   exception.HostBinaryNotFound)
    def service_get_all_by(self, context, topic=None, host=None, binary=None):
        if not any((topic, host, binary)):
            result = self.db.service_get_all(context)
        elif all((topic, host)):
            if topic == 'compute':
                result = self.db.service_get_by_compute_host(context, host)
                # FIXME(comstud) Potentially remove this on bump to v2.0
                result = [result]
            else:
                result = self.db.service_get_by_host_and_topic(context,
                                                               host, topic)
        elif all((host, binary)):
            result = self.db.service_get_by_args(context, host, binary)
        elif topic:
            result = self.db.service_get_all_by_topic(context, topic)
        elif host:
            result = self.db.service_get_all_by_host(context, host)

        return jsonutils.to_primitive(result)

    @messaging.expected_exceptions(exception.InstanceActionNotFound)
    def action_event_start(self, context, values):
        evt = self.db.action_event_start(context, values)
        return jsonutils.to_primitive(evt)

    @messaging.expected_exceptions(exception.InstanceActionNotFound,
                                   exception.InstanceActionEventNotFound)
    def action_event_finish(self, context, values):
        evt = self.db.action_event_finish(context, values)
        return jsonutils.to_primitive(evt)

    def service_create(self, context, values):
        svc = self.db.service_create(context, values)
        return jsonutils.to_primitive(svc)

    @messaging.expected_exceptions(exception.ServiceNotFound)
    def service_destroy(self, context, service_id):
        self.db.service_destroy(context, service_id)

    def compute_node_create(self, context, values):
        result = self.db.compute_node_create(context, values)
        return jsonutils.to_primitive(result)

    def compute_node_update(self, context, node, values, prune_stats=False):
        # NOTE(belliott) prune_stats is no longer relevant and will be
        # ignored
        if isinstance(values.get('stats'), dict):
            # NOTE(danms): In Icehouse, the 'stats' was changed from a dict
            # to a JSON string. If we get a dict-based value, convert it to
            # JSON, which the lower layers now expect. This can be removed
            # in version 2.0 of the RPC API
            values['stats'] = jsonutils.dumps(values['stats'])

        result = self.db.compute_node_update(context, node['id'], values)
        return jsonutils.to_primitive(result)

    def compute_node_delete(self, context, node):
        result = self.db.compute_node_delete(context, node['id'])
        return jsonutils.to_primitive(result)

    @messaging.expected_exceptions(exception.ServiceNotFound)
    def service_update(self, context, service, values):
        svc = self.db.service_update(context, service['id'], values)
        return jsonutils.to_primitive(svc)

    def task_log_get(self, context, task_name, begin, end, host, state=None):
        result = self.db.task_log_get(context, task_name, begin, end, host,
                                      state)
        return jsonutils.to_primitive(result)

    def task_log_begin_task(self, context, task_name, begin, end, host,
                            task_items=None, message=None):
        result = self.db.task_log_begin_task(context.elevated(), task_name,
                                             begin, end, host, task_items,
                                             message)
        return jsonutils.to_primitive(result)

    def task_log_end_task(self, context, task_name, begin, end, host,
                          errors, message=None):
        result = self.db.task_log_end_task(context.elevated(), task_name,
                                           begin, end, host, errors, message)
        return jsonutils.to_primitive(result)

    def notify_usage_exists(self, context, instance, current_period=False,
                            ignore_missing_network_data=True,
                            system_metadata=None, extra_usage_info=None):
        compute_utils.notify_usage_exists(self.notifier, context, instance,
                                          current_period,
                                          ignore_missing_network_data,
                                          system_metadata, extra_usage_info)

    def security_groups_trigger_handler(self, context, event, args):
        self.security_group_api.trigger_handler(event, context, *args)

    def security_groups_trigger_members_refresh(self, context, group_ids):
        self.security_group_api.trigger_members_refresh(context, group_ids)

    def network_migrate_instance_start(self, context, instance, migration):
        self.network_api.migrate_instance_start(context, instance, migration)

    def network_migrate_instance_finish(self, context, instance, migration):
        self.network_api.migrate_instance_finish(context, instance, migration)

    def quota_commit(self, context, reservations, project_id=None,
                     user_id=None):
        quota.QUOTAS.commit(context, reservations, project_id=project_id,
                            user_id=user_id)

    def quota_rollback(self, context, reservations, project_id=None,
                       user_id=None):
        quota.QUOTAS.rollback(context, reservations, project_id=project_id,
                              user_id=user_id)

    def get_ec2_ids(self, context, instance):
        ec2_ids = {}

        ec2_ids['instance-id'] = ec2utils.id_to_ec2_inst_id(instance['uuid'])
        ec2_ids['ami-id'] = ec2utils.glance_id_to_ec2_id(context,
                                                         instance['image_ref'])
        for image_type in ['kernel', 'ramdisk']:
            image_id = instance.get('%s_id' % image_type)
            if image_id is not None:
                ec2_image_type = ec2utils.image_type(image_type)
                ec2_id = ec2utils.glance_id_to_ec2_id(context, image_id,
                                                      ec2_image_type)
                ec2_ids['%s-id' % image_type] = ec2_id

        return ec2_ids

    # NOTE(danms): This method is now deprecated and can be removed in
    # version v2.0 of the RPC API
    def compute_stop(self, context, instance, do_cast=True):
        # NOTE(mriedem): Clients using an interface before 1.43 will be sending
        # dicts so we need to handle that here since compute/api::stop()
        # requires an object.
        if isinstance(instance, dict):
            instance = instance_obj.Instance._from_db_object(
                                context, instance_obj.Instance(), instance)
        self.compute_api.stop(context, instance, do_cast)

    # NOTE(comstud): This method is now deprecated and can be removed in
    # version v2.0 of the RPC API
    def compute_confirm_resize(self, context, instance, migration_ref):
        if isinstance(instance, dict):
            attrs = ['metadata', 'system_metadata', 'info_cache',
                     'security_groups']
            instance = instance_obj.Instance._from_db_object(
                                context, instance_obj.Instance(), instance,
                                expected_attrs=attrs)
        if isinstance(migration_ref, dict):
            migration_ref = migration_obj.Migration._from_db_object(
                                context.elevated(), migration_ref)
        self.compute_api.confirm_resize(context, instance,
                                        migration=migration_ref)

    def compute_unrescue(self, context, instance):
        self.compute_api.unrescue(context, instance)

    def _object_dispatch(self, target, method, context, args, kwargs):
        """Dispatch a call to an object method.

        This ensures that object methods get called and any exception
        that is raised gets wrapped in an ExpectedException for forwarding
        back to the caller (without spamming the conductor logs).
        """
        try:
            # NOTE(danms): Keep the getattr inside the try block since
            # a missing method is really a client problem
            return getattr(target, method)(context, *args, **kwargs)
        except Exception:
            raise messaging.ExpectedException()

    def object_class_action(self, context, objname, objmethod,
                            objver, args, kwargs):
        """Perform a classmethod action on an object."""
        objclass = nova_object.NovaObject.obj_class_from_name(objname,
                                                              objver)
        result = self._object_dispatch(objclass, objmethod, context,
                                       args, kwargs)
        # NOTE(danms): The RPC layer will convert to primitives for us,
        # but in this case, we need to honor the version the client is
        # asking for, so we do it before returning here.
        return (result.obj_to_primitive(target_version=objver)
                if isinstance(result, nova_object.NovaObject) else result)

    def object_action(self, context, objinst, objmethod, args, kwargs):
        """Perform an action on an object."""
        oldobj = objinst.obj_clone()
        result = self._object_dispatch(objinst, objmethod, context,
                                       args, kwargs)
        updates = dict()
        # NOTE(danms): Diff the object with the one passed to us and
        # generate a list of changes to forward back
        for name, field in objinst.fields.items():
            if not objinst.obj_attr_is_set(name):
                # Avoid demand-loading anything
                continue
            if (not oldobj.obj_attr_is_set(name) or
                    oldobj[name] != objinst[name]):
                updates[name] = field.to_primitive(objinst, name,
                                                   objinst[name])
        # This is safe since a field named this would conflict with the
        # method anyway
        updates['obj_what_changed'] = objinst.obj_what_changed()
        return updates, result

    # NOTE(danms): This method is now deprecated and can be removed in
    # v2.0 of the RPC API
    def compute_reboot(self, context, instance, reboot_type):
        self.compute_api.reboot(context, instance, reboot_type)

    def object_backport(self, context, objinst, target_version):
        return objinst.obj_to_primitive(target_version=target_version)


class ComputeTaskManager(base.Base):
    """Namespace for compute methods.

    This class presents an rpc API for nova-conductor under the 'compute_task'
    namespace.  The methods here are compute operations that are invoked
    by the API service.  These methods see the operation to completion, which
    may involve coordinating activities on multiple compute nodes.
    """

    target = messaging.Target(namespace='compute_task', version='1.6')

    def __init__(self):
        super(ComputeTaskManager, self).__init__()
        self.compute_rpcapi = compute_rpcapi.ComputeAPI()
        self.scheduler_rpcapi = scheduler_rpcapi.SchedulerAPI()
        self.image_service = glance.get_default_image_service()

    @messaging.expected_exceptions(exception.NoValidHost,
                                   exception.ComputeServiceUnavailable,
                                   exception.InvalidHypervisorType,
                                   exception.UnableToMigrateToSelf,
                                   exception.DestinationHypervisorTooOld,
                                   exception.InvalidLocalStorage,
                                   exception.InvalidSharedStorage,
                                   exception.MigrationPreCheckError)
    def migrate_server(self, context, instance, scheduler_hint, live, rebuild,
            flavor, block_migration, disk_over_commit, reservations=None):
        if instance and not isinstance(instance, instance_obj.Instance):
            # NOTE(danms): Until v2 of the RPC API, we need to tolerate
            # old-world instance objects here
            attrs = ['metadata', 'system_metadata', 'info_cache',
                     'security_groups']
            instance = instance_obj.Instance._from_db_object(
                context, instance_obj.Instance(), instance,
                expected_attrs=attrs)
        if live and not rebuild and not flavor:
            self._live_migrate(context, instance, scheduler_hint,
                               block_migration, disk_over_commit)
        elif not live and not rebuild and flavor:
            instance_uuid = instance['uuid']
            with compute_utils.EventReporter(context, self.db,
                                         'cold_migrate', instance_uuid):
                self._cold_migrate(context, instance, flavor,
                                   scheduler_hint['filter_properties'],
                                   reservations)
        else:
            raise NotImplementedError()

    def _cold_migrate(self, context, instance, flavor, filter_properties,
                      reservations):
        image_ref = instance.image_ref
        image = compute_utils.get_image_metadata(
            context, self.image_service, image_ref, instance)

        request_spec = scheduler_utils.build_request_spec(
            context, image, [instance], instance_type=flavor)

        quotas = quotas_obj.Quotas.from_reservations(context,
                                                     reservations,
                                                     instance=instance)
        try:
            hosts = self.scheduler_rpcapi.select_destinations(
                    context, request_spec, filter_properties)
            host_state = hosts[0]
        except exception.NoValidHost as ex:
            vm_state = instance['vm_state']
            if not vm_state:
                vm_state = vm_states.ACTIVE
            updates = {'vm_state': vm_state, 'task_state': None}
            self._set_vm_state_and_notify(context, 'migrate_server',
                                          updates, ex, request_spec)
            quotas.rollback()

            LOG.warning(_("No valid host found for cold migrate"),
                        instance=instance)
            return

        try:
            scheduler_utils.populate_filter_properties(filter_properties,
                                                       host_state)
            # context is not serializable
            filter_properties.pop('context', None)

            # TODO(timello): originally, instance_type in request_spec
            # on compute.api.resize does not have 'extra_specs', so we
            # remove it for now to keep tests backward compatibility.
            request_spec['instance_type'].pop('extra_specs')

            (host, node) = (host_state['host'], host_state['nodename'])
            self.compute_rpcapi.prep_resize(
                context, image, instance,
                flavor, host,
                reservations, request_spec=request_spec,
                filter_properties=filter_properties, node=node)
        except Exception as ex:
            with excutils.save_and_reraise_exception():
                updates = {'vm_state': instance['vm_state'],
                           'task_state': None}
                self._set_vm_state_and_notify(context, 'migrate_server',
                                              updates, ex, request_spec)
                quotas.rollback()

    def _set_vm_state_and_notify(self, context, method, updates, ex,
                                 request_spec):
        scheduler_utils.set_vm_state_and_notify(
                context, 'compute_task', method, updates,
                ex, request_spec, self.db)

    def _live_migrate(self, context, instance, scheduler_hint,
                      block_migration, disk_over_commit):
        destination = scheduler_hint.get("host")
        try:
            live_migrate.execute(context, instance, destination,
                             block_migration, disk_over_commit)
        except (exception.NoValidHost,
                exception.ComputeServiceUnavailable,
                exception.InvalidHypervisorType,
                exception.InvalidCPUInfo,
                exception.UnableToMigrateToSelf,
                exception.DestinationHypervisorTooOld,
                exception.InvalidLocalStorage,
                exception.InvalidSharedStorage,
                exception.HypervisorUnavailable,
                exception.MigrationPreCheckError) as ex:
            with excutils.save_and_reraise_exception():
                #TODO(johngarbutt) - eventually need instance actions here
                request_spec = {'instance_properties': {
                    'uuid': instance['uuid'], },
                }
                scheduler_utils.set_vm_state_and_notify(context,
                        'compute_task', 'migrate_server',
                        dict(vm_state=instance['vm_state'],
                             task_state=None,
                             expected_task_state=task_states.MIGRATING,),
                        ex, request_spec, self.db)
        except Exception as ex:
            LOG.error(_('Migration of instance %(instance_id)s to host'
                       ' %(dest)s unexpectedly failed.'),
                       {'instance_id': instance['uuid'], 'dest': destination},
                       exc_info=True)
            raise exception.MigrationError(reason=ex)

    def build_instances(self, context, instances, image, filter_properties,
            admin_password, injected_files, requested_networks,
            security_groups, block_device_mapping, legacy_bdm=True):
        request_spec = scheduler_utils.build_request_spec(context, image,
                                                          instances)
        # NOTE(alaski): For compatibility until a new scheduler method is used.
        request_spec.update({'block_device_mapping': block_device_mapping,
                             'security_group': security_groups})
        self.scheduler_rpcapi.run_instance(context, request_spec=request_spec,
                admin_password=admin_password, injected_files=injected_files,
                requested_networks=requested_networks, is_first_time=True,
                filter_properties=filter_properties,
                legacy_bdm_in_spec=legacy_bdm)

    def _get_image(self, context, image_id):
        if not image_id:
            return None
        return self.image_service.show(context, image_id)

    def _delete_image(self, context, image_id):
        (image_service, image_id) = glance.get_remote_image_service(context,
                image_id)
        return image_service.delete(context, image_id)

    def _schedule_instances(self, context, image, filter_properties,
            *instances):
        request_spec = scheduler_utils.build_request_spec(context, image,
                instances)
        # dict(host='', nodename='', limits='')
        hosts = self.scheduler_rpcapi.select_destinations(context,
                request_spec, filter_properties)
        return hosts

    def unshelve_instance(self, context, instance):
        sys_meta = instance.system_metadata

        if instance.vm_state == vm_states.SHELVED:
            instance.task_state = task_states.POWERING_ON
            instance.save(expected_task_state=task_states.UNSHELVING)
            self.compute_rpcapi.start_instance(context, instance)
            snapshot_id = sys_meta.get('shelved_image_id')
            if snapshot_id:
                self._delete_image(context, snapshot_id)
        elif instance.vm_state == vm_states.SHELVED_OFFLOADED:
            try:
                with compute_utils.EventReporter(context, self.db,
                        'get_image_info', instance.uuid):
                    image = self._get_image(context,
                            sys_meta['shelved_image_id'])
            except exception.ImageNotFound:
                with excutils.save_and_reraise_exception():
                    LOG.error(_('Unshelve attempted but vm_state not SHELVED '
                                'or SHELVED_OFFLOADED'), instance=instance)
                    instance.vm_state = vm_states.ERROR
                    instance.save()

            try:
                with compute_utils.EventReporter(context, self.db,
                                                 'schedule_instances',
                                                 instance.uuid):
                    filter_properties = {}
                    hosts = self._schedule_instances(context, image,
                                                     filter_properties,
                                                     instance)
                    host_state = hosts[0]
                    scheduler_utils.populate_filter_properties(
                            filter_properties, host_state)
                    (host, node) = (host_state['host'], host_state['nodename'])
                    self.compute_rpcapi.unshelve_instance(
                            context, instance, host, image=image,
                            filter_properties=filter_properties, node=node)
            except exception.NoValidHost as ex:
                instance.task_state = None
                instance.save()
                LOG.warning(_("No valid host found for unshelve instance"),
                            instance=instance)
                return
        else:
            LOG.error(_('Unshelve attempted but vm_state not SHELVED or '
                        'SHELVED_OFFLOADED'), instance=instance)
            instance.vm_state = vm_states.ERROR
            instance.save()
            return

        for key in ['shelved_at', 'shelved_image_id', 'shelved_host']:
            if key in sys_meta:
                del(sys_meta[key])
        instance.system_metadata = sys_meta
        instance.save()


class _ConductorManagerV2Proxy(object):

    target = messaging.Target(version='2.0')

    def __init__(self, manager):
        self.manager = manager

    def instance_update(self, context, instance_uuid, updates,
                        service):
        return self.manager.instance_update(context, instance_uuid, updates,
                service)

    def instance_get_by_uuid(self, context, instance_uuid,
                             columns_to_join):
        return self.manager.instance_get_by_uuid(context, instance_uuid,
                columns_to_join)

    def migration_get_in_progress_by_host_and_node(self, context,
                                                   host, node):
        return self.manager.migration_get_in_progress_by_host_and_node(context,
                host, node)

    def aggregate_host_add(self, context, aggregate, host):
        return self.manager.aggregate_host_add(context, aggregate, host)

    def aggregate_host_delete(self, context, aggregate, host):
        return self.manager.aggregate_host_delete(context, aggregate, host)

    def aggregate_metadata_get_by_host(self, context, host, key):
        return self.manager.aggregate_metadata_get_by_host(context, host, key)

    def bw_usage_update(self, context, uuid, mac, start_period,
                        bw_in, bw_out, last_ctr_in, last_ctr_out,
                        last_refreshed, update_cells):
        return self.manager.bw_usage_update(context, uuid, mac, start_period,
                bw_in, bw_out, last_ctr_in, last_ctr_out, last_refreshed,
                update_cells)

    def provider_fw_rule_get_all(self, context):
        return self.manager.provider_fw_rule_get_all(context)

    def agent_build_get_by_triple(self, context, hypervisor, os, architecture):
        return self.manager.agent_build_get_by_triple(context, hypervisor, os,
                architecture)

    def block_device_mapping_update_or_create(self, context, values, create):
        return self.manager.block_device_mapping_update_or_create(context,
                values, create)

    def block_device_mapping_get_all_by_instance(self, context, instance,
                                                 legacy):
        return self.manager.block_device_mapping_get_all_by_instance(context,
                instance, legacy)

    def instance_get_all_by_filters(self, context, filters, sort_key,
                                    sort_dir, columns_to_join, use_slave):
        return self.manager.instance_get_all_by_filters(context, filters,
                sort_key, sort_dir, columns_to_join, use_slave)

    def instance_get_active_by_window_joined(self, context, begin, end,
                                             project_id, host):
        return self.manager.instance_get_active_by_window_joined(context,
                begin, end, project_id, host)

    def instance_destroy(self, context, instance):
        return self.manager.instance_destroy(context, instance)

    def instance_info_cache_delete(self, context, instance):
        return self.manager.instance_info_cache_delete(context, instance)

    def vol_get_usage_by_time(self, context, start_time):
        return self.manager.vol_get_usage_by_time(context, start_time)

    def vol_usage_update(self, context, vol_id, rd_req, rd_bytes, wr_req,
                         wr_bytes, instance, last_refreshed, update_totals):
        return self.manager.vol_usage_update(context, vol_id, rd_req, rd_bytes,
                wr_req, wr_bytes, instance, last_refreshed, update_totals)

    def service_get_all_by(self, context, topic, host, binary):
        return self.manager.service_get_all_by(context, topic, host, binary)

    def instance_get_all_by_host(self, context, host, node, columns_to_join):
        return self.manager.instance_get_all_by_host(context, host, node,
                columns_to_join)

    def instance_fault_create(self, context, values):
        return self.manager.instance_fault_create(context, values)

    def action_event_start(self, context, values):
        return self.manager.action_event_start(context, values)

    def action_event_finish(self, context, values):
        return self.manager.action_event_finish(context, values)

    def service_create(self, context, values):
        return self.manager.service_create(context, values)

    def service_destroy(self, context, service_id):
        return self.manager.service_destroy(context, service_id)

    def compute_node_create(self, context, values):
        return self.manager.compute_node_create(context, values)

    def compute_node_update(self, context, node, values):
        return self.manager.compute_node_update(context, node, values)

    def compute_node_delete(self, context, node):
        return self.manager.compute_node_delete(context, node)

    def service_update(self, context, service, values):
        return self.manager.service_update(context, service, values)

    def task_log_get(self, context, task_name, begin, end, host, state):
        return self.manager.task_log_get(context, task_name, begin, end, host,
                state)

    def task_log_begin_task(self, context, task_name, begin, end, host,
                            task_items, message):
        return self.manager.task_log_begin_task(context, task_name, begin, end,
                host, task_items, message)

    def task_log_end_task(self, context, task_name, begin, end, host, errors,
                          message):
        return self.manager.task_log_end_task(context, task_name, begin, end,
                host, errors, message)

    def notify_usage_exists(self, context, instance, current_period,
                            ignore_missing_network_data,
                            system_metadata, extra_usage_info):
        return self.manager.notify_usage_exists(context, instance,
                current_period, ignore_missing_network_data, system_metadata,
                extra_usage_info)

    def security_groups_trigger_handler(self, context, event, args):
        return self.manager.security_groups_trigger_handler(context, event,
                args)

    def security_groups_trigger_members_refresh(self, context, group_ids):
        return self.manager.security_groups_trigger_members_refresh(context,
                group_ids)

    def network_migrate_instance_start(self, context, instance, migration):
        return self.manager.network_migrate_instance_start(context, instance,
                migration)

    def network_migrate_instance_finish(self, context, instance, migration):
        return self.manager.network_migrate_instance_finish(context, instance,
                migration)

    def quota_commit(self, context, reservations, project_id, user_id):
        return self.manager.quota_commit(context, reservations, project_id,
                user_id)

    def quota_rollback(self, context, reservations, project_id, user_id):
        return self.manager.quota_rollback(context, reservations, project_id,
                user_id)

    def get_ec2_ids(self, context, instance):
        return self.manager.get_ec2_ids(context, instance)

    def compute_unrescue(self, context, instance):
        return self.manager.compute_unrescue(context, instance)

    def object_class_action(self, context, objname, objmethod, objver,
                            args, kwargs):
        return self.manager.object_class_action(context, objname, objmethod,
                objver, args, kwargs)

    def object_action(self, context, objinst, objmethod, args, kwargs):
        return self.manager.object_action(context, objinst, objmethod, args,
                kwargs)

    def object_backport(self, context, objinst, target_version):
        return self.manager.object_backport(context, objinst, target_version)
