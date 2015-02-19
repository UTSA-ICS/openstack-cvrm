# Copyright (c) 2014 VMware, Inc.
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

import mock
import six.moves.urllib.parse as urlparse

from oslo.utils import units
from oslo.vmware import constants
from oslo.vmware.objects import datastore
from oslo.vmware import vim_util
from tests import base


class HostMount(object):

    def __init__(self, key, mountInfo):
        self.key = key
        self.mountInfo = mountInfo


class MountInfo(object):

    def __init__(self, accessMode, mounted, accessible):
        self.accessMode = accessMode
        self.mounted = mounted
        self.accessible = accessible


class DatastoreTestCase(base.TestCase):

    """Test the Datastore object."""

    def test_ds(self):
        ds = datastore.Datastore(
            "fake_ref", "ds_name", 2 * units.Gi, 1 * units.Gi)
        self.assertEqual('ds_name', ds.name)
        self.assertEqual('fake_ref', ds.ref)
        self.assertEqual(2 * units.Gi, ds.capacity)
        self.assertEqual(1 * units.Gi, ds.freespace)

    def test_ds_invalid_space(self):
        self.assertRaises(ValueError, datastore.Datastore,
                          "fake_ref", "ds_name", 1 * units.Gi, 2 * units.Gi)
        self.assertRaises(ValueError, datastore.Datastore,
                          "fake_ref", "ds_name", None, 2 * units.Gi)

    def test_ds_no_capacity_no_freespace(self):
        ds = datastore.Datastore("fake_ref", "ds_name")
        self.assertIsNone(ds.capacity)
        self.assertIsNone(ds.freespace)

    def test_ds_invalid(self):
        self.assertRaises(ValueError, datastore.Datastore, None, "ds_name")
        self.assertRaises(ValueError, datastore.Datastore, "fake_ref", None)

    def test_build_path(self):
        ds = datastore.Datastore("fake_ref", "ds_name")
        ds_path = ds.build_path("some_dir", "foo.vmdk")
        self.assertEqual('[ds_name] some_dir/foo.vmdk', str(ds_path))

    def test_build_url(self):
        ds = datastore.Datastore("fake_ref", "ds_name")
        path = 'images/ubuntu.vmdk'
        self.assertRaises(ValueError, ds.build_url, 'https', '10.0.0.2', path)
        ds.datacenter = mock.Mock()
        ds.datacenter.name = "dc_path"
        ds_url = ds.build_url('https', '10.0.0.2', path)
        self.assertEqual(ds_url.datastore_name, "ds_name")
        self.assertEqual(ds_url.datacenter_path, "dc_path")
        self.assertEqual(ds_url.path, path)

    def test_get_summary(self):
        ds_ref = vim_util.get_moref('ds-0', 'Datastore')
        ds = datastore.Datastore(ds_ref, 'ds-name')
        summary = mock.sentinel.summary
        session = mock.Mock()
        session.invoke_api = mock.Mock()
        session.invoke_api.return_value = summary
        ret = ds.get_summary(session)
        self.assertEqual(summary, ret)
        session.invoke_api.assert_called_once_with(vim_util,
                                                   'get_object_property',
                                                   session.vim,
                                                   ds.ref, 'summary')

    def test_get_connected_hosts(self):
        session = mock.Mock()
        ds_ref = vim_util.get_moref('ds-0', 'Datastore')
        ds = datastore.Datastore(ds_ref, 'ds-name')
        ds.get_summary = mock.Mock()
        ds.get_summary.return_value.accessible = False
        self.assertEqual([], ds.get_connected_hosts(session))
        ds.get_summary.return_value.accessible = True
        m1 = HostMount("m1", MountInfo('readWrite', True, True))
        m2 = HostMount("m2", MountInfo('read', True, True))
        m3 = HostMount("m3", MountInfo('readWrite', False, True))
        m4 = HostMount("m4", MountInfo('readWrite', True, False))
        ds.get_summary.assert_called_once_with(session)

        class Prop(object):
            DatastoreHostMount = [m1, m2, m3, m4]
        session.invoke_api = mock.Mock()
        session.invoke_api.return_value = Prop()
        hosts = ds.get_connected_hosts(session)
        self.assertEqual(1, len(hosts))
        self.assertEqual("m1", hosts.pop())

    def test_is_datastore_mount_usable(self):
        m = MountInfo('readWrite', True, True)
        self.assertTrue(datastore.Datastore.is_datastore_mount_usable(m))
        m = MountInfo('read', True, True)
        self.assertFalse(datastore.Datastore.is_datastore_mount_usable(m))
        m = MountInfo('readWrite', False, True)
        self.assertFalse(datastore.Datastore.is_datastore_mount_usable(m))
        m = MountInfo('readWrite', True, False)
        self.assertFalse(datastore.Datastore.is_datastore_mount_usable(m))
        m = MountInfo('readWrite', False, False)
        self.assertFalse(datastore.Datastore.is_datastore_mount_usable(m))
        m = MountInfo('readWrite', None, None)
        self.assertFalse(datastore.Datastore.is_datastore_mount_usable(m))
        m = MountInfo('readWrite', None, True)
        self.assertFalse(datastore.Datastore.is_datastore_mount_usable(m))


class DatastorePathTestCase(base.TestCase):

    """Test the DatastorePath object."""

    def test_ds_path(self):
        p = datastore.DatastorePath('dsname', 'a/b/c', 'file.iso')
        self.assertEqual('[dsname] a/b/c/file.iso', str(p))
        self.assertEqual('a/b/c/file.iso', p.rel_path)
        self.assertEqual('a/b/c', p.parent.rel_path)
        self.assertEqual('[dsname] a/b/c', str(p.parent))
        self.assertEqual('dsname', p.datastore)
        self.assertEqual('file.iso', p.basename)
        self.assertEqual('a/b/c', p.dirname)

    def test_ds_path_no_ds_name(self):
        bad_args = [
            ('', ['a/b/c', 'file.iso']),
            (None, ['a/b/c', 'file.iso'])]
        for t in bad_args:
            self.assertRaises(
                ValueError, datastore.DatastorePath,
                t[0], *t[1])

    def test_ds_path_invalid_path_components(self):
        bad_args = [
            ('dsname', [None]),
            ('dsname', ['', None]),
            ('dsname', ['a', None]),
            ('dsname', ['a', None, 'b']),
            ('dsname', [None, '']),
            ('dsname', [None, 'b'])]

        for t in bad_args:
            self.assertRaises(
                ValueError, datastore.DatastorePath,
                t[0], *t[1])

    def test_ds_path_no_subdir(self):
        args = [
            ('dsname', ['', 'x.vmdk']),
            ('dsname', ['x.vmdk'])]

        canonical_p = datastore.DatastorePath('dsname', 'x.vmdk')
        self.assertEqual('[dsname] x.vmdk', str(canonical_p))
        self.assertEqual('', canonical_p.dirname)
        self.assertEqual('x.vmdk', canonical_p.basename)
        self.assertEqual('x.vmdk', canonical_p.rel_path)
        for t in args:
            p = datastore.DatastorePath(t[0], *t[1])
            self.assertEqual(str(canonical_p), str(p))

    def test_ds_path_ds_only(self):
        args = [
            ('dsname', []),
            ('dsname', ['']),
            ('dsname', ['', ''])]

        canonical_p = datastore.DatastorePath('dsname')
        self.assertEqual('[dsname]', str(canonical_p))
        self.assertEqual('', canonical_p.rel_path)
        self.assertEqual('', canonical_p.basename)
        self.assertEqual('', canonical_p.dirname)
        for t in args:
            p = datastore.DatastorePath(t[0], *t[1])
            self.assertEqual(str(canonical_p), str(p))
            self.assertEqual(canonical_p.rel_path, p.rel_path)

    def test_ds_path_equivalence(self):
        args = [
            ('dsname', ['a/b/c/', 'x.vmdk']),
            ('dsname', ['a/', 'b/c/', 'x.vmdk']),
            ('dsname', ['a', 'b', 'c', 'x.vmdk']),
            ('dsname', ['a/b/c', 'x.vmdk'])]

        canonical_p = datastore.DatastorePath('dsname', 'a/b/c', 'x.vmdk')
        for t in args:
            p = datastore.DatastorePath(t[0], *t[1])
            self.assertEqual(str(canonical_p), str(p))
            self.assertEqual(canonical_p.datastore, p.datastore)
            self.assertEqual(canonical_p.rel_path, p.rel_path)
            self.assertEqual(str(canonical_p.parent), str(p.parent))

    def test_ds_path_non_equivalence(self):
        args = [
            # leading slash
            ('dsname', ['/a', 'b', 'c', 'x.vmdk']),
            ('dsname', ['/a/b/c/', 'x.vmdk']),
            ('dsname', ['a/b/c', '/x.vmdk']),
            # leading space
            ('dsname', ['a/b/c/', ' x.vmdk']),
            ('dsname', ['a/', ' b/c/', 'x.vmdk']),
            ('dsname', [' a', 'b', 'c', 'x.vmdk']),
            # trailing space
            ('dsname', ['/a/b/c/', 'x.vmdk ']),
            ('dsname', ['a/b/c/ ', 'x.vmdk'])]

        canonical_p = datastore.DatastorePath('dsname', 'a/b/c', 'x.vmdk')
        for t in args:
            p = datastore.DatastorePath(t[0], *t[1])
            self.assertNotEqual(str(canonical_p), str(p))

    def test_equal(self):
        a = datastore.DatastorePath('ds_name', 'a')
        b = datastore.DatastorePath('ds_name', 'a')
        self.assertEqual(a, b)

    def test_join(self):
        p = datastore.DatastorePath('ds_name', 'a')
        ds_path = p.join('b')
        self.assertEqual('[ds_name] a/b', str(ds_path))

        p = datastore.DatastorePath('ds_name', 'a')
        ds_path = p.join()
        bad_args = [
            [None],
            ['', None],
            ['a', None],
            ['a', None, 'b']]
        for arg in bad_args:
            self.assertRaises(ValueError, p.join, *arg)

    def test_ds_path_parse(self):
        p = datastore.DatastorePath.parse('[dsname]')
        self.assertEqual('dsname', p.datastore)
        self.assertEqual('', p.rel_path)

        p = datastore.DatastorePath.parse('[dsname] folder')
        self.assertEqual('dsname', p.datastore)
        self.assertEqual('folder', p.rel_path)

        p = datastore.DatastorePath.parse('[dsname] folder/file')
        self.assertEqual('dsname', p.datastore)
        self.assertEqual('folder/file', p.rel_path)

        for p in [None, '']:
            self.assertRaises(ValueError, datastore.DatastorePath.parse, p)

        for p in ['bad path', '/a/b/c', 'a/b/c']:
            self.assertRaises(IndexError, datastore.DatastorePath.parse, p)


class DatastoreURLTestCase(base.TestCase):

    """Test the DatastoreURL object."""

    def test_path_strip(self):
        scheme = 'https'
        server = '13.37.73.31'
        path = 'images/ubuntu-14.04.vmdk'
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = datastore.DatastoreURL(scheme, server, path, dc_path, ds_name)
        expected_url = '%s://%s/folder/%s?%s' % (
            scheme, server, path, query)
        self.assertEqual(expected_url, str(url))

    def test_path_lstrip(self):
        scheme = 'https'
        server = '13.37.73.31'
        path = '/images/ubuntu-14.04.vmdk'
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = datastore.DatastoreURL(scheme, server, path, dc_path, ds_name)
        expected_url = '%s://%s/folder/%s?%s' % (
            scheme, server, path.lstrip('/'), query)
        self.assertEqual(expected_url, str(url))

    def test_path_rstrip(self):
        scheme = 'https'
        server = '13.37.73.31'
        path = 'images/ubuntu-14.04.vmdk/'
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = datastore.DatastoreURL(scheme, server, path, dc_path, ds_name)
        expected_url = '%s://%s/folder/%s?%s' % (
            scheme, server, path.rstrip('/'), query)
        self.assertEqual(expected_url, str(url))

    def test_urlparse(self):
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = 'https://13.37.73.31/folder/images/aa.vmdk?%s' % query
        ds_url = datastore.DatastoreURL.urlparse(url)
        self.assertEqual(url, str(ds_url))

    def test_datastore_name(self):
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = 'https://13.37.73.31/folder/images/aa.vmdk?%s' % query
        ds_url = datastore.DatastoreURL.urlparse(url)
        self.assertEqual(ds_name, ds_url.datastore_name)

    def test_datacenter_path(self):
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = 'https://13.37.73.31/folder/images/aa.vmdk?%s' % query
        ds_url = datastore.DatastoreURL.urlparse(url)
        self.assertEqual(dc_path, ds_url.datacenter_path)

    def test_path(self):
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        path = 'images/aa.vmdk'
        query = urlparse.urlencode(params)
        url = 'https://13.37.73.31/folder/%s?%s' % (path, query)
        ds_url = datastore.DatastoreURL.urlparse(url)
        self.assertEqual(path, ds_url.path)

    @mock.patch('six.moves.http_client.HTTPSConnection')
    def test_connect(self, mock_conn):
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = 'https://13.37.73.31/folder/images/aa.vmdk?%s' % query
        ds_url = datastore.DatastoreURL.urlparse(url)
        cookie = mock.Mock()
        ds_url.connect('PUT', 128, cookie)
        mock_conn.assert_called_once_with('13.37.73.31')

    def test_get_transfer_ticket(self):
        dc_path = 'datacenter-1'
        ds_name = 'datastore-1'
        params = {'dcPath': dc_path, 'dsName': ds_name}
        query = urlparse.urlencode(params)
        url = 'https://13.37.73.31/folder/images/aa.vmdk?%s' % query
        session = mock.Mock()
        session.invoke_api = mock.Mock()

        class Ticket(object):
            id = 'fake_id'
        session.invoke_api.return_value = Ticket()
        ds_url = datastore.DatastoreURL.urlparse(url)
        ticket = ds_url.get_transfer_ticket(session, 'PUT')
        self.assertEqual('%s="%s"' % (constants.CGI_COOKIE_KEY, 'fake_id'),
                         ticket)
