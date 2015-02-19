#    Copyright 2010 OpenStack Foundation
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

from lxml import etree

import time
import uuid

from nova.openstack.common.gettextutils import _

# Allow passing None to the various connect methods
# (i.e. allow the client to rely on default URLs)
allow_default_uri_connection = True

# string indicating the CPU arch
node_arch = 'x86_64'  # or 'i686' (or whatever else uname -m might return)

# memory size in kilobytes
node_kB_mem = 4096

# the number of active CPUs
node_cpus = 2

# expected CPU frequency
node_mhz = 800

# the number of NUMA cell, 1 for unusual NUMA topologies or uniform
# memory access; check capabilities XML for the actual NUMA topology
node_nodes = 1  # NUMA nodes

# number of CPU sockets per node if nodes > 1, total number of CPU
# sockets otherwise
node_sockets = 1

# number of cores per socket
node_cores = 2

# number of threads per core
node_threads = 1

# CPU model
node_cpu_model = "Penryn"

# CPU vendor
node_cpu_vendor = "Intel"

# Has libvirt connection been used at least once
connection_used = False


def _reset():
    global allow_default_uri_connection
    allow_default_uri_connection = True

# virDomainState
VIR_DOMAIN_NOSTATE = 0
VIR_DOMAIN_RUNNING = 1
VIR_DOMAIN_BLOCKED = 2
VIR_DOMAIN_PAUSED = 3
VIR_DOMAIN_SHUTDOWN = 4
VIR_DOMAIN_SHUTOFF = 5
VIR_DOMAIN_CRASHED = 6

VIR_DOMAIN_XML_SECURE = 1

VIR_DOMAIN_EVENT_ID_LIFECYCLE = 0

VIR_DOMAIN_EVENT_DEFINED = 0
VIR_DOMAIN_EVENT_UNDEFINED = 1
VIR_DOMAIN_EVENT_STARTED = 2
VIR_DOMAIN_EVENT_SUSPENDED = 3
VIR_DOMAIN_EVENT_RESUMED = 4
VIR_DOMAIN_EVENT_STOPPED = 5
VIR_DOMAIN_EVENT_SHUTDOWN = 6
VIR_DOMAIN_EVENT_PMSUSPENDED = 7

VIR_DOMAIN_UNDEFINE_MANAGED_SAVE = 1

VIR_DOMAIN_AFFECT_CURRENT = 0
VIR_DOMAIN_AFFECT_LIVE = 1
VIR_DOMAIN_AFFECT_CONFIG = 2

VIR_CPU_COMPARE_ERROR = -1
VIR_CPU_COMPARE_INCOMPATIBLE = 0
VIR_CPU_COMPARE_IDENTICAL = 1
VIR_CPU_COMPARE_SUPERSET = 2

VIR_CRED_USERNAME = 1
VIR_CRED_AUTHNAME = 2
VIR_CRED_LANGUAGE = 3
VIR_CRED_CNONCE = 4
VIR_CRED_PASSPHRASE = 5
VIR_CRED_ECHOPROMPT = 6
VIR_CRED_NOECHOPROMPT = 7
VIR_CRED_REALM = 8
VIR_CRED_EXTERNAL = 9

VIR_MIGRATE_PEER2PEER = 2
VIR_MIGRATE_UNDEFINE_SOURCE = 16

VIR_NODE_CPU_STATS_ALL_CPUS = -1

VIR_DOMAIN_START_PAUSED = 1

# libvirtError enums
# (Intentionally different from what's in libvirt. We do this to check,
#  that consumers of the library are using the symbolic names rather than
#  hardcoding the numerical values)
VIR_FROM_QEMU = 100
VIR_FROM_DOMAIN = 200
VIR_FROM_NWFILTER = 330
VIR_FROM_REMOTE = 340
VIR_FROM_RPC = 345
VIR_ERR_NO_SUPPORT = 3
VIR_ERR_XML_DETAIL = 350
VIR_ERR_NO_DOMAIN = 420
VIR_ERR_OPERATION_INVALID = 55
VIR_ERR_OPERATION_TIMEOUT = 68
VIR_ERR_NO_NWFILTER = 620
VIR_ERR_SYSTEM_ERROR = 900
VIR_ERR_INTERNAL_ERROR = 950

# Readonly
VIR_CONNECT_RO = 1

# virConnectBaselineCPU flags
VIR_CONNECT_BASELINE_CPU_EXPAND_FEATURES = 1

# snapshotCreateXML flags
VIR_DOMAIN_SNAPSHOT_CREATE_NO_METADATA = 4
VIR_DOMAIN_SNAPSHOT_CREATE_DISK_ONLY = 16
VIR_DOMAIN_SNAPSHOT_CREATE_REUSE_EXT = 32
VIR_DOMAIN_SNAPSHOT_CREATE_QUIESCE = 64


def _parse_disk_info(element):
    disk_info = {}
    disk_info['type'] = element.get('type', 'file')
    disk_info['device'] = element.get('device', 'disk')

    driver = element.find('./driver')
    if driver is not None:
        disk_info['driver_name'] = driver.get('name')
        disk_info['driver_type'] = driver.get('type')

    source = element.find('./source')
    if source is not None:
        disk_info['source'] = source.get('file')
        if not disk_info['source']:
            disk_info['source'] = source.get('dev')

        if not disk_info['source']:
            disk_info['source'] = source.get('path')

    target = element.find('./target')
    if target is not None:
        disk_info['target_dev'] = target.get('dev')
        disk_info['target_bus'] = target.get('bus')

    return disk_info


class libvirtError(Exception):
    """This class was copied and slightly modified from
    `libvirt-python:libvirt-override.py`.

    Since a test environment will use the real `libvirt-python` version of
    `libvirtError` if it's installed and not this fake, we need to maintain
    strict compatability with the original class, including `__init__` args
    and instance-attributes.

    To create a libvirtError instance you should:

        # Create an unsupported error exception
        exc = libvirtError('my message')
        exc.err = (libvirt.VIR_ERR_NO_SUPPORT,)

    self.err is a tuple of form:
        (error_code, error_domain, error_message, error_level, str1, str2,
         str3, int1, int2)

    Alternatively, you can use the `make_libvirtError` convenience function to
    allow you to specify these attributes in one shot.
    """
    def __init__(self, defmsg, conn=None, dom=None, net=None, pool=None,
                 vol=None):
        Exception.__init__(self, defmsg)
        self.err = None

    def get_error_code(self):
        if self.err is None:
            return None
        return self.err[0]

    def get_error_domain(self):
        if self.err is None:
            return None
        return self.err[1]

    def get_error_message(self):
        if self.err is None:
            return None
        return self.err[2]

    def get_error_level(self):
        if self.err is None:
            return None
        return self.err[3]

    def get_str1(self):
        if self.err is None:
            return None
        return self.err[4]

    def get_str2(self):
        if self.err is None:
            return None
        return self.err[5]

    def get_str3(self):
        if self.err is None:
            return None
        return self.err[6]

    def get_int1(self):
        if self.err is None:
            return None
        return self.err[7]

    def get_int2(self):
        if self.err is None:
            return None
        return self.err[8]


class NWFilter(object):
    def __init__(self, connection, xml):
        self._connection = connection

        self._xml = xml
        self._parse_xml(xml)

    def _parse_xml(self, xml):
        tree = etree.fromstring(xml)
        root = tree.find('.')
        self._name = root.get('name')

    def undefine(self):
        self._connection._remove_filter(self)


class Domain(object):
    def __init__(self, connection, xml, running=False, transient=False):
        self._connection = connection
        if running:
            connection._mark_running(self)

        self._state = running and VIR_DOMAIN_RUNNING or VIR_DOMAIN_SHUTOFF
        self._transient = transient
        self._def = self._parse_definition(xml)
        self._has_saved_state = False
        self._snapshots = {}
        self._id = self._connection._id_counter

    def _parse_definition(self, xml):
        try:
            tree = etree.fromstring(xml)
        except etree.ParseError:
            raise make_libvirtError(
                    libvirtError, "Invalid XML.",
                    error_code=VIR_ERR_XML_DETAIL,
                    error_domain=VIR_FROM_DOMAIN)

        definition = {}

        name = tree.find('./name')
        if name is not None:
            definition['name'] = name.text

        uuid_elem = tree.find('./uuid')
        if uuid_elem is not None:
            definition['uuid'] = uuid_elem.text
        else:
            definition['uuid'] = str(uuid.uuid4())

        vcpu = tree.find('./vcpu')
        if vcpu is not None:
            definition['vcpu'] = int(vcpu.text)

        memory = tree.find('./memory')
        if memory is not None:
            definition['memory'] = int(memory.text)

        os = {}
        os_type = tree.find('./os/type')
        if os_type is not None:
            os['type'] = os_type.text
            os['arch'] = os_type.get('arch', node_arch)

        os_kernel = tree.find('./os/kernel')
        if os_kernel is not None:
            os['kernel'] = os_kernel.text

        os_initrd = tree.find('./os/initrd')
        if os_initrd is not None:
            os['initrd'] = os_initrd.text

        os_cmdline = tree.find('./os/cmdline')
        if os_cmdline is not None:
            os['cmdline'] = os_cmdline.text

        os_boot = tree.find('./os/boot')
        if os_boot is not None:
            os['boot_dev'] = os_boot.get('dev')

        definition['os'] = os

        features = {}

        acpi = tree.find('./features/acpi')
        if acpi is not None:
            features['acpi'] = True

        definition['features'] = features

        devices = {}

        device_nodes = tree.find('./devices')
        if device_nodes is not None:
            disks_info = []
            disks = device_nodes.findall('./disk')
            for disk in disks:
                disks_info += [_parse_disk_info(disk)]
            devices['disks'] = disks_info

            nics_info = []
            nics = device_nodes.findall('./interface')
            for nic in nics:
                nic_info = {}
                nic_info['type'] = nic.get('type')

                mac = nic.find('./mac')
                if mac is not None:
                    nic_info['mac'] = mac.get('address')

                source = nic.find('./source')
                if source is not None:
                    if nic_info['type'] == 'network':
                        nic_info['source'] = source.get('network')
                    elif nic_info['type'] == 'bridge':
                        nic_info['source'] = source.get('bridge')

                nics_info += [nic_info]

            devices['nics'] = nics_info

        definition['devices'] = devices

        return definition

    def create(self):
        self.createWithFlags(0)

    def createWithFlags(self, flags):
        # FIXME: Not handling flags at the moment
        self._state = VIR_DOMAIN_RUNNING
        self._connection._mark_running(self)
        self._has_saved_state = False

    def isActive(self):
        return int(self._state == VIR_DOMAIN_RUNNING)

    def undefine(self):
        self._connection._undefine(self)

    def undefineFlags(self, flags):
        self.undefine()
        if flags & VIR_DOMAIN_UNDEFINE_MANAGED_SAVE:
            if self.hasManagedSaveImage(0):
                self.managedSaveRemove()

    def destroy(self):
        self._state = VIR_DOMAIN_SHUTOFF
        self._connection._mark_not_running(self)

    def ID(self):
        return self._id

    def name(self):
        return self._def['name']

    def UUIDString(self):
        return self._def['uuid']

    def interfaceStats(self, device):
        return [10000242400, 1234, 0, 2, 213412343233, 34214234, 23, 3]

    def blockStats(self, device):
        return [2, 10000242400, 234, 2343424234, 34]

    def suspend(self):
        self._state = VIR_DOMAIN_PAUSED

    def shutdown(self):
        self._state = VIR_DOMAIN_SHUTDOWN
        self._connection._mark_not_running(self)

    def reset(self, flags):
        # FIXME: Not handling flags at the moment
        self._state = VIR_DOMAIN_RUNNING
        self._connection._mark_running(self)

    def info(self):
        return [self._state,
                long(self._def['memory']),
                long(self._def['memory']),
                self._def['vcpu'],
                123456789L]

    def migrateToURI(self, desturi, flags, dname, bandwidth):
        raise make_libvirtError(
                libvirtError,
                "Migration always fails for fake libvirt!",
                error_code=VIR_ERR_INTERNAL_ERROR,
                error_domain=VIR_FROM_QEMU)

    def attachDevice(self, xml):
        disk_info = _parse_disk_info(etree.fromstring(xml))
        disk_info['_attached'] = True
        self._def['devices']['disks'] += [disk_info]
        return True

    def attachDeviceFlags(self, xml, flags):
        if (flags & VIR_DOMAIN_AFFECT_LIVE and
                self._state != VIR_DOMAIN_RUNNING):
            raise make_libvirtError(
                libvirtError,
                "AFFECT_LIVE only allowed for running domains!",
                error_code=VIR_ERR_INTERNAL_ERROR,
                error_domain=VIR_FROM_QEMU)
        self.attachDevice(xml)

    def detachDevice(self, xml):
        disk_info = _parse_disk_info(etree.fromstring(xml))
        disk_info['_attached'] = True
        return disk_info in self._def['devices']['disks']

    def detachDeviceFlags(self, xml, _flags):
        self.detachDevice(xml)

    def XMLDesc(self, flags):
        disks = ''
        for disk in self._def['devices']['disks']:
            disks += '''<disk type='%(type)s' device='%(device)s'>
      <driver name='%(driver_name)s' type='%(driver_type)s'/>
      <source file='%(source)s'/>
      <target dev='%(target_dev)s' bus='%(target_bus)s'/>
      <address type='drive' controller='0' bus='0' unit='0'/>
    </disk>''' % disk

        nics = ''
        for nic in self._def['devices']['nics']:
            nics += '''<interface type='%(type)s'>
      <mac address='%(mac)s'/>
      <source %(type)s='%(source)s'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x03'
               function='0x0'/>
    </interface>''' % nic

        return '''<domain type='kvm'>
  <name>%(name)s</name>
  <uuid>%(uuid)s</uuid>
  <memory>%(memory)s</memory>
  <currentMemory>%(memory)s</currentMemory>
  <vcpu>%(vcpu)s</vcpu>
  <os>
    <type arch='%(arch)s' machine='pc-0.12'>hvm</type>
    <boot dev='hd'/>
  </os>
  <features>
    <acpi/>
    <apic/>
    <pae/>
  </features>
  <clock offset='localtime'/>
  <on_poweroff>destroy</on_poweroff>
  <on_reboot>restart</on_reboot>
  <on_crash>restart</on_crash>
  <devices>
    <emulator>/usr/bin/kvm</emulator>
    %(disks)s
    <controller type='ide' index='0'>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x01'
               function='0x1'/>
    </controller>
    %(nics)s
    <serial type='file'>
      <source path='dummy.log'/>
      <target port='0'/>
    </serial>
    <serial type='pty'>
      <source pty='/dev/pts/27'/>
      <target port='1'/>
    </serial>
    <console type='file'>
      <source path='dummy.log'/>
      <target port='0'/>
    </console>
    <input type='tablet' bus='usb'/>
    <input type='mouse' bus='ps2'/>
    <graphics type='vnc' port='-1' autoport='yes'/>
    <graphics type='spice' port='-1' autoport='yes'/>
    <video>
      <model type='cirrus' vram='9216' heads='1'/>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x02'
               function='0x0'/>
    </video>
    <memballoon model='virtio'>
      <address type='pci' domain='0x0000' bus='0x00' slot='0x04'
               function='0x0'/>
    </memballoon>
  </devices>
</domain>''' % {'name': self._def['name'],
                'uuid': self._def['uuid'],
                'memory': self._def['memory'],
                'vcpu': self._def['vcpu'],
                'arch': self._def['os']['arch'],
                'disks': disks,
                'nics': nics}

    def managedSave(self, flags):
        self._connection._mark_not_running(self)
        self._has_saved_state = True

    def managedSaveRemove(self, flags):
        self._has_saved_state = False

    def hasManagedSaveImage(self, flags):
        return int(self._has_saved_state)

    def resume(self):
        self._state = VIR_DOMAIN_RUNNING

    def snapshotCreateXML(self, xml, flags):
        tree = etree.fromstring(xml)
        name = tree.find('./name').text
        snapshot = DomainSnapshot(name, self)
        self._snapshots[name] = snapshot
        return snapshot

    def vcpus(self):
        vcpus = ([], [])
        for i in range(0, self._def['vcpu']):
            vcpus[0].append((i, 1, 120405L, i))
            vcpus[1].append((True, True, True, True))
        return vcpus

    def memoryStats(self):
        return {}

    def maxMemory(self):
        return self._def['memory']

    def blockJobInfo(self, disk, flags):
        return {}


class DomainSnapshot(object):
    def __init__(self, name, domain):
        self._name = name
        self._domain = domain

    def delete(self, flags):
        del self._domain._snapshots[self._name]


class Connection(object):
    def __init__(self, uri=None, readonly=False, version=9007):
        if not uri or uri == '':
            if allow_default_uri_connection:
                uri = 'qemu:///session'
            else:
                raise ValueError("URI was None, but fake libvirt is "
                                 "configured to not accept this.")

        uri_whitelist = ['qemu:///system',
                         'qemu:///session',
                         'xen:///system',
                         'uml:///system',
                         'test:///default']

        if uri not in uri_whitelist:
            raise make_libvirtError(
                    libvirtError,
                   "libvirt error: no connection driver "
                   "available for No connection for URI %s" % uri,
                   error_code=5, error_domain=0)

        self.readonly = readonly
        self._uri = uri
        self._vms = {}
        self._running_vms = {}
        self._id_counter = 1  # libvirt reserves 0 for the hypervisor.
        self._nwfilters = {}
        self._event_callbacks = {}
        self.fakeLibVersion = version
        self.fakeVersion = version

    def _add_filter(self, nwfilter):
        self._nwfilters[nwfilter._name] = nwfilter

    def _remove_filter(self, nwfilter):
        del self._nwfilters[nwfilter._name]

    def _mark_running(self, dom):
        self._running_vms[self._id_counter] = dom
        self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_STARTED, 0)
        self._id_counter += 1

    def _mark_not_running(self, dom):
        if dom._transient:
            self._undefine(dom)

        dom._id = -1

        for (k, v) in self._running_vms.iteritems():
            if v == dom:
                del self._running_vms[k]
                self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_STOPPED, 0)
                return

    def _undefine(self, dom):
        del self._vms[dom.name()]
        if not dom._transient:
            self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_UNDEFINED, 0)

    def getInfo(self):
        return [node_arch,
                node_kB_mem,
                node_cpus,
                node_mhz,
                node_nodes,
                node_sockets,
                node_cores,
                node_threads]

    def numOfDomains(self):
        return len(self._running_vms)

    def listDomainsID(self):
        return self._running_vms.keys()

    def lookupByID(self, id):
        if id in self._running_vms:
            return self._running_vms[id]
        raise make_libvirtError(
                libvirtError,
                'Domain not found: no domain with matching id %d' % id,
                error_code=VIR_ERR_NO_DOMAIN,
                error_domain=VIR_FROM_QEMU)

    def lookupByName(self, name):
        if name in self._vms:
            return self._vms[name]
        raise make_libvirtError(
                libvirtError,
                'Domain not found: no domain with matching name "%s"' % name,
                error_code=VIR_ERR_NO_DOMAIN,
                error_domain=VIR_FROM_QEMU)

    def _emit_lifecycle(self, dom, event, detail):
        if VIR_DOMAIN_EVENT_ID_LIFECYCLE not in self._event_callbacks:
            return

        cbinfo = self._event_callbacks[VIR_DOMAIN_EVENT_ID_LIFECYCLE]
        callback = cbinfo[0]
        opaque = cbinfo[1]
        callback(self, dom, event, detail, opaque)

    def defineXML(self, xml):
        dom = Domain(connection=self, running=False, transient=False, xml=xml)
        self._vms[dom.name()] = dom
        self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_DEFINED, 0)
        return dom

    def createXML(self, xml, flags):
        dom = Domain(connection=self, running=True, transient=True, xml=xml)
        self._vms[dom.name()] = dom
        self._emit_lifecycle(dom, VIR_DOMAIN_EVENT_STARTED, 0)
        return dom

    def getType(self):
        if self._uri == 'qemu:///system':
            return 'QEMU'

    def getLibVersion(self):
        return self.fakeLibVersion

    def getVersion(self):
        return self.fakeVersion

    def getHostname(self):
        return 'compute1'

    def domainEventRegisterAny(self, dom, eventid, callback, opaque):
        self._event_callbacks[eventid] = [callback, opaque]

    def registerCloseCallback(self, cb, opaque):
        pass

    def getCapabilities(self):
        """Return spoofed capabilities."""
        return '''<capabilities>
  <host>
    <uuid>cef19ce0-0ca2-11df-855d-b19fbce37686</uuid>
    <cpu>
      <arch>x86_64</arch>
      <model>Penryn</model>
      <vendor>Intel</vendor>
      <topology sockets='1' cores='2' threads='1'/>
      <feature name='xtpr'/>
      <feature name='tm2'/>
      <feature name='est'/>
      <feature name='vmx'/>
      <feature name='ds_cpl'/>
      <feature name='monitor'/>
      <feature name='pbe'/>
      <feature name='tm'/>
      <feature name='ht'/>
      <feature name='ss'/>
      <feature name='acpi'/>
      <feature name='ds'/>
      <feature name='vme'/>
    </cpu>
    <migration_features>
      <live/>
      <uri_transports>
        <uri_transport>tcp</uri_transport>
      </uri_transports>
    </migration_features>
    <secmodel>
      <model>apparmor</model>
      <doi>0</doi>
    </secmodel>
  </host>

  <guest>
    <os_type>hvm</os_type>
    <arch name='i686'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu</emulator>
      <machine>pc-0.14</machine>
      <machine canonical='pc-0.14'>pc</machine>
      <machine>pc-0.13</machine>
      <machine>pc-0.12</machine>
      <machine>pc-0.11</machine>
      <machine>pc-0.10</machine>
      <machine>isapc</machine>
      <domain type='qemu'>
      </domain>
      <domain type='kvm'>
        <emulator>/usr/bin/kvm</emulator>
        <machine>pc-0.14</machine>
        <machine canonical='pc-0.14'>pc</machine>
        <machine>pc-0.13</machine>
        <machine>pc-0.12</machine>
        <machine>pc-0.11</machine>
        <machine>pc-0.10</machine>
        <machine>isapc</machine>
      </domain>
    </arch>
    <features>
      <cpuselection/>
      <deviceboot/>
      <pae/>
      <nonpae/>
      <acpi default='on' toggle='yes'/>
      <apic default='on' toggle='no'/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='x86_64'>
      <wordsize>64</wordsize>
      <emulator>/usr/bin/qemu-system-x86_64</emulator>
      <machine>pc-0.14</machine>
      <machine canonical='pc-0.14'>pc</machine>
      <machine>pc-0.13</machine>
      <machine>pc-0.12</machine>
      <machine>pc-0.11</machine>
      <machine>pc-0.10</machine>
      <machine>isapc</machine>
      <domain type='qemu'>
      </domain>
      <domain type='kvm'>
        <emulator>/usr/bin/kvm</emulator>
        <machine>pc-0.14</machine>
        <machine canonical='pc-0.14'>pc</machine>
        <machine>pc-0.13</machine>
        <machine>pc-0.12</machine>
        <machine>pc-0.11</machine>
        <machine>pc-0.10</machine>
        <machine>isapc</machine>
      </domain>
    </arch>
    <features>
      <cpuselection/>
      <deviceboot/>
      <acpi default='on' toggle='yes'/>
      <apic default='on' toggle='no'/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='arm'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-arm</emulator>
      <machine>integratorcp</machine>
      <machine>vexpress-a9</machine>
      <machine>syborg</machine>
      <machine>musicpal</machine>
      <machine>mainstone</machine>
      <machine>n800</machine>
      <machine>n810</machine>
      <machine>n900</machine>
      <machine>cheetah</machine>
      <machine>sx1</machine>
      <machine>sx1-v1</machine>
      <machine>beagle</machine>
      <machine>beaglexm</machine>
      <machine>tosa</machine>
      <machine>akita</machine>
      <machine>spitz</machine>
      <machine>borzoi</machine>
      <machine>terrier</machine>
      <machine>connex</machine>
      <machine>verdex</machine>
      <machine>lm3s811evb</machine>
      <machine>lm3s6965evb</machine>
      <machine>realview-eb</machine>
      <machine>realview-eb-mpcore</machine>
      <machine>realview-pb-a8</machine>
      <machine>realview-pbx-a9</machine>
      <machine>versatilepb</machine>
      <machine>versatileab</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='mips'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-mips</emulator>
      <machine>malta</machine>
      <machine>mipssim</machine>
      <machine>magnum</machine>
      <machine>pica61</machine>
      <machine>mips</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='mipsel'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-mipsel</emulator>
      <machine>malta</machine>
      <machine>mipssim</machine>
      <machine>magnum</machine>
      <machine>pica61</machine>
      <machine>mips</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='sparc'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-sparc</emulator>
      <machine>SS-5</machine>
      <machine>leon3_generic</machine>
      <machine>SS-10</machine>
      <machine>SS-600MP</machine>
      <machine>SS-20</machine>
      <machine>Voyager</machine>
      <machine>LX</machine>
      <machine>SS-4</machine>
      <machine>SPARCClassic</machine>
      <machine>SPARCbook</machine>
      <machine>SS-1000</machine>
      <machine>SS-2000</machine>
      <machine>SS-2</machine>
      <domain type='qemu'>
      </domain>
    </arch>
  </guest>

  <guest>
    <os_type>hvm</os_type>
    <arch name='ppc'>
      <wordsize>32</wordsize>
      <emulator>/usr/bin/qemu-system-ppc</emulator>
      <machine>g3beige</machine>
      <machine>virtex-ml507</machine>
      <machine>mpc8544ds</machine>
      <machine canonical='bamboo-0.13'>bamboo</machine>
      <machine>bamboo-0.13</machine>
      <machine>bamboo-0.12</machine>
      <machine>ref405ep</machine>
      <machine>taihu</machine>
      <machine>mac99</machine>
      <machine>prep</machine>
      <domain type='qemu'>
      </domain>
    </arch>
    <features>
      <deviceboot/>
    </features>
  </guest>

</capabilities>'''

    def compareCPU(self, xml, flags):
        tree = etree.fromstring(xml)

        arch_node = tree.find('./arch')
        if arch_node is not None:
            if arch_node.text not in ['x86_64', 'i686']:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        model_node = tree.find('./model')
        if model_node is not None:
            if model_node.text != node_cpu_model:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        vendor_node = tree.find('./vendor')
        if vendor_node is not None:
            if vendor_node.text != node_cpu_vendor:
                return VIR_CPU_COMPARE_INCOMPATIBLE

        # The rest of the stuff libvirt implements is rather complicated
        # and I don't think it adds much value to replicate it here.

        return VIR_CPU_COMPARE_IDENTICAL

    def getCPUStats(self, cpuNum, flag):
        if cpuNum < 2:
            return {'kernel': 5664160000000L,
                    'idle': 1592705190000000L,
                    'user': 26728850000000L,
                    'iowait': 6121490000000L}
        else:
            raise make_libvirtError(
                    libvirtError,
                    "invalid argument: Invalid cpu number",
                    error_code=VIR_ERR_INTERNAL_ERROR,
                    error_domain=VIR_FROM_QEMU)

    def nwfilterLookupByName(self, name):
        try:
            return self._nwfilters[name]
        except KeyError:
            raise make_libvirtError(
                    libvirtError,
                    "no nwfilter with matching name %s" % name,
                    error_code=VIR_ERR_NO_NWFILTER,
                    error_domain=VIR_FROM_NWFILTER)

    def nwfilterDefineXML(self, xml):
        nwfilter = NWFilter(self, xml)
        self._add_filter(nwfilter)

    def listDefinedDomains(self):
        return []

    def listDevices(self, cap, flags):
        return []

    def baselineCPU(self, cpu, flag):
        """Add new libvirt API."""
        return """<cpu mode='custom' match='exact'>
                    <model fallback='allow'>Westmere</model>
                    <vendor>Intel</vendor>
                    <feature policy='require' name='aes'/>
                  </cpu>"""


def openAuth(uri, auth, flags):

    if type(auth) != list:
        raise Exception(_("Expected a list for 'auth' parameter"))

    if type(auth[0]) != list:
        raise Exception(
            _("Expected a function in 'auth[0]' parameter"))

    if not callable(auth[1]):
        raise Exception(
            _("Expected a function in 'auth[1]' parameter"))

    connection_used = True

    return Connection(uri, (flags == VIR_CONNECT_RO))


def virEventRunDefaultImpl():
    time.sleep(1)


def virEventRegisterDefaultImpl():
    if connection_used:
        raise Exception(_("virEventRegisterDefaultImpl() must be \
            called before connection is used."))


def registerErrorHandler(handler, ctxt):
    pass


def make_libvirtError(error_class, msg, error_code=None,
                       error_domain=None, error_message=None,
                       error_level=None, str1=None, str2=None, str3=None,
                       int1=None, int2=None):
    """Convenience function for creating `libvirtError` exceptions which
    allow you to specify arguments in constructor without having to manipulate
    the `err` tuple directly.

    We need to pass in `error_class` to this function because it may be
    `libvirt.libvirtError` or `fakelibvirt.libvirtError` depending on whether
    `libvirt-python` is installed.
    """
    exc = error_class(msg)
    exc.err = (error_code, error_domain, error_message, error_level,
               str1, str2, str3, int1, int2)
    return exc


virDomain = Domain


virConnect = Connection
