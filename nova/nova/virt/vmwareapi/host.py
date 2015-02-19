# Copyright (c) 2013 Hewlett-Packard Development Company, L.P.
# Copyright (c) 2012 VMware, Inc.
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

"""
Management class for host-related functions (start, reboot, etc).
"""

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import units
from nova import utils
from nova.virt.vmwareapi import vim_util
from nova.virt.vmwareapi import vm_util

LOG = logging.getLogger(__name__)


class Host(object):
    """Implements host related operations."""
    def __init__(self, session):
        self._session = session

    def host_power_action(self, host, action):
        """Reboots or shuts down the host."""
        host_mor = vm_util.get_host_ref(self._session)
        LOG.debug(_("%(action)s %(host)s"), {'action': action, 'host': host})
        if action == "reboot":
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "RebootHost_Task", host_mor,
                                    force=False)
        elif action == "shutdown":
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "ShutdownHost_Task", host_mor,
                                    force=False)
        elif action == "startup":
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "PowerUpHostFromStandBy_Task", host_mor,
                                    timeoutSec=60)
        self._session._wait_for_task(host_task)

    def host_maintenance_mode(self, host, mode):
        """Start/Stop host maintenance window. On start, it triggers
        guest VMs evacuation.
        """
        host_mor = vm_util.get_host_ref(self._session)
        LOG.debug(_("Set maintenance mod on %(host)s to %(mode)s"),
                  {'host': host, 'mode': mode})
        if mode:
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "EnterMaintenanceMode_Task",
                                    host_mor, timeout=0,
                                    evacuatePoweredOffVms=True)
        else:
            host_task = self._session._call_method(
                                    self._session._get_vim(),
                                    "ExitMaintenanceMode_Task",
                                    host_mor, timeout=0)
        self._session._wait_for_task(host_task)

    def set_host_enabled(self, _host, enabled):
        """Sets the specified host's ability to accept new instances."""
        pass


class HostState(object):
    """Manages information about the ESX host this compute
    node is running on.
    """
    def __init__(self, session, host_name):
        super(HostState, self).__init__()
        self._session = session
        self._host_name = host_name
        self._stats = {}
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh or not self._stats:
            self.update_status()
        return self._stats

    def update_status(self):
        """Update the current state of the host.
        """
        host_mor = vm_util.get_host_ref(self._session)
        summary = self._session._call_method(vim_util,
                                             "get_dynamic_property",
                                             host_mor,
                                             "HostSystem",
                                             "summary")

        if summary is None:
            return

        try:
            ds = vm_util.get_datastore_ref_and_name(self._session)
        except exception.DatastoreNotFound:
            ds = (None, None, 0, 0)

        data = {}
        data["vcpus"] = summary.hardware.numCpuThreads
        data["cpu_info"] = \
                {"vendor": summary.hardware.vendor,
                 "model": summary.hardware.cpuModel,
                 "topology": {"cores": summary.hardware.numCpuCores,
                              "sockets": summary.hardware.numCpuPkgs,
                              "threads": summary.hardware.numCpuThreads}
                }
        data["disk_total"] = ds[2] / units.Gi
        data["disk_available"] = ds[3] / units.Gi
        data["disk_used"] = data["disk_total"] - data["disk_available"]
        data["host_memory_total"] = summary.hardware.memorySize / units.Mi
        data["host_memory_free"] = data["host_memory_total"] - \
                                   summary.quickStats.overallMemoryUsage
        data["hypervisor_type"] = summary.config.product.name
        data["hypervisor_version"] = utils.convert_version_to_int(
                str(summary.config.product.version))
        data["hypervisor_hostname"] = self._host_name
        data["supported_instances"] = [('i686', 'vmware', 'hvm'),
                                       ('x86_64', 'vmware', 'hvm')]

        self._stats = data
        return data


class VCState(object):
    """Manages information about the VC host this compute
    node is running on.
    """
    def __init__(self, session, host_name, cluster):
        super(VCState, self).__init__()
        self._session = session
        self._host_name = host_name
        self._cluster = cluster
        self._stats = {}
        self.update_status()

    def get_host_stats(self, refresh=False):
        """Return the current state of the host. If 'refresh' is
        True, run the update first.
        """
        if refresh or not self._stats:
            self.update_status()
        return self._stats

    def update_status(self):
        """Update the current state of the cluster."""
        # Get the datastore in the cluster
        try:
            ds = vm_util.get_datastore_ref_and_name(self._session,
                                                    self._cluster)
        except exception.DatastoreNotFound:
            ds = (None, None, 0, 0)

        # Get cpu, memory stats from the cluster
        stats = vm_util.get_stats_from_cluster(self._session, self._cluster)
        about_info = self._session._call_method(vim_util, "get_about_info")
        data = {}
        data["vcpus"] = stats['cpu']['vcpus']
        data["cpu_info"] = {"vendor": stats['cpu']['vendor'],
                            "model": stats['cpu']['model'],
                            "topology": {"cores": stats['cpu']['cores'],
                                         "threads": stats['cpu']['vcpus']}}
        data["disk_total"] = ds[2] / units.Gi
        data["disk_available"] = ds[3] / units.Gi
        data["disk_used"] = data["disk_total"] - data["disk_available"]
        data["host_memory_total"] = stats['mem']['total']
        data["host_memory_free"] = stats['mem']['free']
        data["hypervisor_type"] = about_info.name
        data["hypervisor_version"] = utils.convert_version_to_int(
                str(about_info.version))
        data["hypervisor_hostname"] = self._host_name
        data["supported_instances"] = [('i686', 'vmware', 'hvm'),
                                       ('x86_64', 'vmware', 'hvm')]

        self._stats = data
        return data
