#    Copyright 2010 United States Government as represented by the
#    Administrator of the National Aeronautics and Space Administration.
#    All Rights Reserved.
#    Copyright (c) 2010 Citrix Systems, Inc.
#    Copyright (c) 2011 Piston Cloud Computing, Inc
#    Copyright (c) 2011 OpenStack Foundation
#    (c) Copyright 2013 Hewlett-Packard Development Company, L.P.
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

import errno
import os
import platform

from lxml import etree
from oslo.config import cfg

from nova import exception
from nova.openstack.common.gettextutils import _
from nova.openstack.common import log as logging
from nova.openstack.common import processutils
from nova.openstack.common import units
from nova import utils
from nova.virt import images
from nova.virt import volumeutils

libvirt_opts = [
    cfg.BoolOpt('snapshot_compression',
                default=False,
                help='Compress snapshot images when possible. This '
                     'currently applies exclusively to qcow2 images',
                deprecated_group='DEFAULT',
                deprecated_name='libvirt_snapshot_compression'),
    ]

CONF = cfg.CONF
CONF.register_opts(libvirt_opts, 'libvirt')
CONF.import_opt('instances_path', 'nova.compute.manager')
LOG = logging.getLogger(__name__)


def execute(*args, **kwargs):
    return utils.execute(*args, **kwargs)


def get_iscsi_initiator():
    return volumeutils.get_iscsi_initiator()


def get_fc_hbas():
    """Get the Fibre Channel HBA information."""
    out = None
    try:
        out, err = execute('systool', '-c', 'fc_host', '-v',
                           run_as_root=True)
    except processutils.ProcessExecutionError as exc:
        # This handles the case where rootwrap is used
        # and systool is not installed
        # 96 = nova.cmd.rootwrap.RC_NOEXECFOUND:
        if exc.exit_code == 96:
            LOG.warn(_("systool is not installed"))
        return []
    except OSError as exc:
        # This handles the case where rootwrap is NOT used
        # and systool is not installed
        if exc.errno == errno.ENOENT:
            LOG.warn(_("systool is not installed"))
        return []

    if out is None:
        raise RuntimeError(_("Cannot find any Fibre Channel HBAs"))

    lines = out.split('\n')
    # ignore the first 2 lines
    lines = lines[2:]
    hbas = []
    hba = {}
    lastline = None
    for line in lines:
        line = line.strip()
        # 2 newlines denotes a new hba port
        if line == '' and lastline == '':
            if len(hba) > 0:
                hbas.append(hba)
                hba = {}
        else:
            val = line.split('=')
            if len(val) == 2:
                key = val[0].strip().replace(" ", "")
                value = val[1].strip()
                hba[key] = value.replace('"', '')
        lastline = line

    return hbas


def get_fc_hbas_info():
    """Get Fibre Channel WWNs and device paths from the system, if any."""
    # Note modern linux kernels contain the FC HBA's in /sys
    # and are obtainable via the systool app
    hbas = get_fc_hbas()
    hbas_info = []
    for hba in hbas:
        wwpn = hba['port_name'].replace('0x', '')
        wwnn = hba['node_name'].replace('0x', '')
        device_path = hba['ClassDevicepath']
        device = hba['ClassDevice']
        hbas_info.append({'port_name': wwpn,
                          'node_name': wwnn,
                          'host_device': device,
                          'device_path': device_path})
    return hbas_info


def get_fc_wwpns():
    """Get Fibre Channel WWPNs from the system, if any."""
    # Note modern linux kernels contain the FC HBA's in /sys
    # and are obtainable via the systool app
    hbas = get_fc_hbas()

    wwpns = []
    if hbas:
        for hba in hbas:
            if hba['port_state'] == 'Online':
                wwpn = hba['port_name'].replace('0x', '')
                wwpns.append(wwpn)

    return wwpns


def get_fc_wwnns():
    """Get Fibre Channel WWNNs from the system, if any."""
    # Note modern linux kernels contain the FC HBA's in /sys
    # and are obtainable via the systool app
    hbas = get_fc_hbas()

    wwnns = []
    if hbas:
        for hba in hbas:
            if hba['port_state'] == 'Online':
                wwnn = hba['node_name'].replace('0x', '')
                wwnns.append(wwnn)

    return wwnns


def create_image(disk_format, path, size):
    """Create a disk image

    :param disk_format: Disk image format (as known by qemu-img)
    :param path: Desired location of the disk image
    :param size: Desired size of disk image. May be given as an int or
                 a string. If given as an int, it will be interpreted
                 as bytes. If it's a string, it should consist of a number
                 with an optional suffix ('K' for Kibibytes,
                 M for Mebibytes, 'G' for Gibibytes, 'T' for Tebibytes).
                 If no suffix is given, it will be interpreted as bytes.
    """
    execute('qemu-img', 'create', '-f', disk_format, path, size)


def create_cow_image(backing_file, path, size=None):
    """Create COW image

    Creates a COW image with the given backing file

    :param backing_file: Existing image on which to base the COW image
    :param path: Desired location of the COW image
    """
    base_cmd = ['qemu-img', 'create', '-f', 'qcow2']
    cow_opts = []
    if backing_file:
        cow_opts += ['backing_file=%s' % backing_file]
        base_details = images.qemu_img_info(backing_file)
    else:
        base_details = None
    # This doesn't seem to get inherited so force it to...
    # http://paste.ubuntu.com/1213295/
    # TODO(harlowja) probably file a bug against qemu-img/qemu
    if base_details and base_details.cluster_size is not None:
        cow_opts += ['cluster_size=%s' % base_details.cluster_size]
    # For now don't inherit this due the following discussion...
    # See: http://www.gossamer-threads.com/lists/openstack/dev/10592
    # if 'preallocation' in base_details:
    #     cow_opts += ['preallocation=%s' % base_details['preallocation']]
    if base_details and base_details.encryption:
        cow_opts += ['encryption=%s' % base_details.encryption]
    if size is not None:
        cow_opts += ['size=%s' % size]
    if cow_opts:
        # Format as a comma separated list
        csv_opts = ",".join(cow_opts)
        cow_opts = ['-o', csv_opts]
    cmd = base_cmd + cow_opts + [path]
    execute(*cmd)


def create_lvm_image(vg, lv, size, sparse=False):
    """Create LVM image.

    Creates a LVM image with given size.

    :param vg: existing volume group which should hold this image
    :param lv: name for this image (logical volume)
    :size: size of image in bytes
    :sparse: create sparse logical volume
    """
    vg_info = get_volume_group_info(vg)
    free_space = vg_info['free']

    def check_size(vg, lv, size):
        if size > free_space:
            raise RuntimeError(_('Insufficient Space on Volume Group %(vg)s.'
                                 ' Only %(free_space)db available,'
                                 ' but %(size)db required'
                                 ' by volume %(lv)s.') %
                               {'vg': vg,
                                'free_space': free_space,
                                'size': size,
                                'lv': lv})

    if sparse:
        preallocated_space = 64 * units.Mi
        check_size(vg, lv, preallocated_space)
        if free_space < size:
            LOG.warning(_('Volume group %(vg)s will not be able'
                          ' to hold sparse volume %(lv)s.'
                          ' Virtual volume size is %(size)db,'
                          ' but free space on volume group is'
                          ' only %(free_space)db.'),
                        {'vg': vg,
                         'free_space': free_space,
                         'size': size,
                         'lv': lv})

        cmd = ('lvcreate', '-L', '%db' % preallocated_space,
                '--virtualsize', '%db' % size, '-n', lv, vg)
    else:
        check_size(vg, lv, size)
        cmd = ('lvcreate', '-L', '%db' % size, '-n', lv, vg)
    execute(*cmd, run_as_root=True, attempts=3)


def import_rbd_image(*args):
    execute('rbd', 'import', *args)


def _run_rbd(*args, **kwargs):
    total = list(args)

    if CONF.libvirt.rbd_user:
        total.extend(['--id', str(CONF.libvirt.rbd_user)])
    if CONF.libvirt.images_rbd_ceph_conf:
        total.extend(['--conf', str(CONF.libvirt.images_rbd_ceph_conf)])

    return utils.execute(*total, **kwargs)


def list_rbd_volumes(pool):
    """List volumes names for given ceph pool.

    :param pool: ceph pool name
    """
    try:
        out, err = _run_rbd('rbd', '-p', pool, 'ls')
    except processutils.ProcessExecutionError:
        # No problem when no volume in rbd pool
        return []

    return [line.strip() for line in out.splitlines()]


def remove_rbd_volumes(pool, *names):
    """Remove one or more rbd volume."""
    for name in names:
        rbd_remove = ['rbd', '-p', pool, 'rm', name]
        try:
            _run_rbd(*rbd_remove, attempts=3, run_as_root=True)
        except processutils.ProcessExecutionError:
            LOG.warn(_("rbd remove %(name)s in pool %(pool)s failed"),
                     {'name': name, 'pool': pool})


def get_volume_group_info(vg):
    """Return free/used/total space info for a volume group in bytes

    :param vg: volume group name
    :returns: A dict containing:
             :total: How big the filesystem is (in bytes)
             :free: How much space is free (in bytes)
             :used: How much space is used (in bytes)
    """

    out, err = execute('vgs', '--noheadings', '--nosuffix',
                       '--separator', '|',
                       '--units', 'b', '-o', 'vg_size,vg_free', vg,
                       run_as_root=True)

    info = out.split('|')
    if len(info) != 2:
        raise RuntimeError(_("vg %s must be LVM volume group") % vg)

    return {'total': int(info[0]),
            'free': int(info[1]),
            'used': int(info[0]) - int(info[1])}


def list_logical_volumes(vg):
    """List logical volumes paths for given volume group.

    :param vg: volume group name
    """
    out, err = execute('lvs', '--noheadings', '-o', 'lv_name', vg,
                       run_as_root=True)

    return [line.strip() for line in out.splitlines()]


def logical_volume_info(path):
    """Get logical volume info.

    :param path: logical volume path
    """
    out, err = execute('lvs', '-o', 'vg_all,lv_all',
                       '--separator', '|', path, run_as_root=True)

    info = [line.split('|') for line in out.splitlines()]

    if len(info) != 2:
        raise RuntimeError(_("Path %s must be LVM logical volume") % path)

    return dict(zip(*info))


def logical_volume_size(path):
    """Get logical volume size in bytes.

    :param path: logical volume path
    """
    out, _err = execute('blockdev', '--getsize64', path, run_as_root=True)

    return int(out)


def _zero_logical_volume(path, volume_size):
    """Write zeros over the specified path

    :param path: logical volume path
    :param size: number of zeros to write
    """
    bs = units.Mi
    direct_flags = ('oflag=direct',)
    sync_flags = ()
    remaining_bytes = volume_size

    # The loop efficiently writes zeros using dd,
    # and caters for versions of dd that don't have
    # the easier to use iflag=count_bytes option.
    while remaining_bytes:
        zero_blocks = remaining_bytes / bs
        seek_blocks = (volume_size - remaining_bytes) / bs
        zero_cmd = ('dd', 'bs=%s' % bs,
                    'if=/dev/zero', 'of=%s' % path,
                    'seek=%s' % seek_blocks, 'count=%s' % zero_blocks)
        zero_cmd += direct_flags
        zero_cmd += sync_flags
        if zero_blocks:
            utils.execute(*zero_cmd, run_as_root=True)
        remaining_bytes %= bs
        bs /= units.Ki  # Limit to 3 iterations
        # Use O_DIRECT with initial block size and fdatasync otherwise
        direct_flags = ()
        sync_flags = ('conv=fdatasync',)


def clear_logical_volume(path):
    """Obfuscate the logical volume.

    :param path: logical volume path
    """
    volume_clear = CONF.libvirt.volume_clear

    if volume_clear not in ('none', 'shred', 'zero'):
        LOG.error(_("ignoring unrecognized volume_clear='%s' value"),
                  volume_clear)
        volume_clear = 'zero'

    if volume_clear == 'none':
        return

    volume_clear_size = int(CONF.libvirt.volume_clear_size) * units.Mi
    volume_size = logical_volume_size(path)

    if volume_clear_size != 0 and volume_clear_size < volume_size:
        volume_size = volume_clear_size

    if volume_clear == 'zero':
        # NOTE(p-draigbrady): we could use shred to do the zeroing
        # with -n0 -z, however only versions >= 8.22 perform as well as dd
        _zero_logical_volume(path, volume_size)
    elif volume_clear == 'shred':
        utils.execute('shred', '-n3', '-s%d' % volume_size, path,
                      run_as_root=True)
    else:
        raise exception.Invalid(_("volume_clear='%s' is not handled")
                                % volume_clear)


def remove_logical_volumes(*paths):
    """Remove one or more logical volume."""

    for path in paths:
        clear_logical_volume(path)

    if paths:
        lvremove = ('lvremove', '-f') + paths
        execute(*lvremove, attempts=3, run_as_root=True)


def pick_disk_driver_name(hypervisor_version, is_block_dev=False):
    """Pick the libvirt primary backend driver name

    If the hypervisor supports multiple backend drivers, then the name
    attribute selects the primary backend driver name, while the optional
    type attribute provides the sub-type.  For example, xen supports a name
    of "tap", "tap2", "phy", or "file", with a type of "aio" or "qcow2",
    while qemu only supports a name of "qemu", but multiple types including
    "raw", "bochs", "qcow2", and "qed".

    :param is_block_dev:
    :returns: driver_name or None
    """
    if CONF.libvirt.virt_type == "xen":
        if is_block_dev:
            return "phy"
        else:
            # 4000000 == 4.0.0
            if hypervisor_version == 4000000:
                return "tap"
            else:
                return "tap2"

    elif CONF.libvirt.virt_type in ('kvm', 'qemu'):
        return "qemu"
    else:
        # UML doesn't want a driver_name set
        return None


def get_disk_size(path):
    """Get the (virtual) size of a disk image

    :param path: Path to the disk image
    :returns: Size (in bytes) of the given disk image as it would be seen
              by a virtual machine.
    """
    size = images.qemu_img_info(path).virtual_size
    return int(size)


def get_disk_backing_file(path, basename=True):
    """Get the backing file of a disk image

    :param path: Path to the disk image
    :returns: a path to the image's backing store
    """
    backing_file = images.qemu_img_info(path).backing_file
    if backing_file and basename:
        backing_file = os.path.basename(backing_file)

    return backing_file


def copy_image(src, dest, host=None):
    """Copy a disk image to an existing directory

    :param src: Source image
    :param dest: Destination path
    :param host: Remote host
    """

    if not host:
        # We shell out to cp because that will intelligently copy
        # sparse files.  I.E. holes will not be written to DEST,
        # rather recreated efficiently.  In addition, since
        # coreutils 8.11, holes can be read efficiently too.
        execute('cp', src, dest)
    else:
        dest = "%s:%s" % (host, dest)
        # Try rsync first as that can compress and create sparse dest files.
        # Note however that rsync currently doesn't read sparse files
        # efficiently: https://bugzilla.samba.org/show_bug.cgi?id=8918
        # At least network traffic is mitigated with compression.
        try:
            # Do a relatively light weight test first, so that we
            # can fall back to scp, without having run out of space
            # on the destination for example.
            execute('rsync', '--sparse', '--compress', '--dry-run', src, dest)
        except processutils.ProcessExecutionError:
            execute('scp', src, dest)
        else:
            execute('rsync', '--sparse', '--compress', src, dest)


def write_to_file(path, contents, umask=None):
    """Write the given contents to a file

    :param path: Destination file
    :param contents: Desired contents of the file
    :param umask: Umask to set when creating this file (will be reset)
    """
    if umask:
        saved_umask = os.umask(umask)

    try:
        with open(path, 'w') as f:
            f.write(contents)
    finally:
        if umask:
            os.umask(saved_umask)


def chown(path, owner):
    """Change ownership of file or directory

    :param path: File or directory whose ownership to change
    :param owner: Desired new owner (given as uid or username)
    """
    execute('chown', owner, path, run_as_root=True)


def extract_snapshot(disk_path, source_fmt, out_path, dest_fmt):
    """Extract a snapshot from a disk image.
    Note that nobody should write to the disk image during this operation.

    :param disk_path: Path to disk image
    :param out_path: Desired path of extracted snapshot
    """
    # NOTE(markmc): ISO is just raw to qemu-img
    if dest_fmt == 'iso':
        dest_fmt = 'raw'

    qemu_img_cmd = ('qemu-img', 'convert', '-f', source_fmt, '-O', dest_fmt)

    # Conditionally enable compression of snapshots.
    if CONF.libvirt.snapshot_compression and dest_fmt == "qcow2":
        qemu_img_cmd += ('-c',)

    qemu_img_cmd += (disk_path, out_path)
    execute(*qemu_img_cmd)


def load_file(path):
    """Read contents of file

    :param path: File to read
    """
    with open(path, 'r') as fp:
        return fp.read()


def file_open(*args, **kwargs):
    """Open file

    see built-in file() documentation for more details

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return file(*args, **kwargs)


def file_delete(path):
    """Delete (unlink) file

    Note: The reason this is kept in a separate module is to easily
          be able to provide a stub module that doesn't alter system
          state at all (for unit tests)
    """
    return os.unlink(path)


def find_disk(virt_dom):
    """Find root device path for instance

    May be file or device
    """
    xml_desc = virt_dom.XMLDesc(0)
    domain = etree.fromstring(xml_desc)
    if CONF.libvirt.virt_type == 'lxc':
        source = domain.find('devices/filesystem/source')
        disk_path = source.get('dir')
        disk_path = disk_path[0:disk_path.rfind('rootfs')]
        disk_path = os.path.join(disk_path, 'disk')
    else:
        source = domain.find('devices/disk/source')
        disk_path = source.get('file') or source.get('dev')
        if not disk_path and CONF.libvirt.images_type == 'rbd':
            disk_path = source.get('name')
            if disk_path:
                disk_path = 'rbd:' + disk_path

    if not disk_path:
        raise RuntimeError(_("Can't retrieve root device path "
                             "from instance libvirt configuration"))

    return disk_path


def get_disk_type(path):
    """Retrieve disk type (raw, qcow2, lvm) for given file."""
    if path.startswith('/dev'):
        return 'lvm'
    elif path.startswith('rbd:'):
        return 'rbd'

    return images.qemu_img_info(path).file_format


def get_fs_info(path):
    """Get free/used/total space info for a filesystem

    :param path: Any dirent on the filesystem
    :returns: A dict containing:

             :free: How much space is free (in bytes)
             :used: How much space is used (in bytes)
             :total: How big the filesystem is (in bytes)
    """
    hddinfo = os.statvfs(path)
    total = hddinfo.f_frsize * hddinfo.f_blocks
    free = hddinfo.f_frsize * hddinfo.f_bavail
    used = hddinfo.f_frsize * (hddinfo.f_blocks - hddinfo.f_bfree)
    return {'total': total,
            'free': free,
            'used': used}


def fetch_image(context, target, image_id, user_id, project_id, max_size=0):
    """Grab image."""
    images.fetch_to_raw(context, image_id, target, user_id, project_id,
                        max_size=max_size)


def get_instance_path(instance, forceold=False, relative=False):
    """Determine the correct path for instance storage.

    This method determines the directory name for instance storage, while
    handling the fact that we changed the naming style to something more
    unique in the grizzly release.

    :param instance: the instance we want a path for
    :param forceold: force the use of the pre-grizzly format
    :param relative: if True, just the relative path is returned

    :returns: a path to store information about that instance
    """
    pre_grizzly_name = os.path.join(CONF.instances_path, instance['name'])
    if forceold or os.path.exists(pre_grizzly_name):
        if relative:
            return instance['name']
        return pre_grizzly_name

    if relative:
        return instance['uuid']
    return os.path.join(CONF.instances_path, instance['uuid'])


def get_arch(image_meta):
    """Determine the architecture of the guest (or host).

    This method determines the CPU architecture that must be supported by
    the hypervisor. It gets the (guest) arch info from image_meta properties,
    and it will fallback to the nova-compute (host) arch if no architecture
    info is provided in image_meta.

    :param image_meta: the metadata associated with the instance image

    :returns: guest (or host) architecture
    """
    if image_meta:
        arch = image_meta.get('properties', {}).get('architecture')
        if arch is not None:
            return arch

    return platform.processor()


def is_mounted(mount_path, source=None):
    """Check if the given source is mounted at given destination point."""
    try:
        check_cmd = ['findmnt', '--target', mount_path]
        if source:
            check_cmd.extend(['--source', source])

        utils.execute(*check_cmd)
        return True
    except processutils.ProcessExecutionError as exc:
        return False
    except OSError as exc:
        #info since it's not required to have this tool.
        if exc.errno == errno.ENOENT:
            LOG.info(_("findmnt tool is not installed"))
        return False
