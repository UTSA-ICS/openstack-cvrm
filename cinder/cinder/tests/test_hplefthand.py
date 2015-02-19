#    (c) Copyright 2014 Hewlett-Packard Development Company, L.P.
#    All Rights Reserved.
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
#
"""Unit tests for OpenStack Cinder volume drivers."""
import mock

from hplefthandclient import exceptions as hpexceptions

from cinder import context
from cinder import exception
from cinder.openstack.common import log as logging
from cinder import test
from cinder import units
from cinder.volume.drivers.san.hp import hp_lefthand_iscsi
from cinder.volume.drivers.san.hp import hp_lefthand_rest_proxy
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


class HPLeftHandBaseDriver():

    cluster_id = 1

    volume_name = "fakevolume"
    volume_id = 1
    volume = {
        'name': volume_name,
        'provider_location': ('10.0.1.6 iqn.2003-10.com.lefthandnetworks:'
                              'group01:25366:fakev 0'),
        'id': volume_id,
        'provider_auth': None,
        'size': 1}

    serverName = 'fakehost'
    server_id = 0

    snapshot_name = "fakeshapshot"
    snapshot_id = 3
    snapshot = {
        'name': snapshot_name,
        'volume_name': volume_name}

    cloned_volume_name = "clone_volume"
    cloned_volume = {'name': cloned_volume_name}

    cloned_snapshot_name = "clonedshapshot"
    cloned_snapshot_id = 5
    cloned_snapshot = {
        'name': cloned_snapshot_name,
        'volume_name': volume_name}

    volume_type_id = 4
    init_iqn = 'iqn.1993-08.org.debian:01:222'

    connector = {
        'ip': '10.0.0.2',
        'initiator': 'iqn.1993-08.org.debian:01:222',
        'host': serverName}

    driver_startup_call_stack = [
        mock.call.login('foo1', 'bar2'),
        mock.call.getClusterByName('CloudCluster1'),
        mock.call.getCluster(1)]


class TestHPLeftHandCLIQISCSIDriver(HPLeftHandBaseDriver, test.TestCase):

    def _fake_cliq_run(self, verb, cliq_args, check_exit_code=True):
        """Return fake results for the various methods."""

        def create_volume(cliq_args):
            """Create volume CLIQ input for test.

            input = "createVolume description="fake description"
                                  clusterName=Cluster01 volumeName=fakevolume
                                  thinProvision=0 output=XML size=1GB"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['thinProvision'], '1')
            self.assertEqual(cliq_args['size'], '1GB')
            return output, None

        def delete_volume(cliq_args):
            """Delete volume CLIQ input for test.

            input = "deleteVolume volumeName=fakevolume prompt=false
                                  output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="164" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['prompt'], 'false')
            return output, None

        def extend_volume(cliq_args):
            """Extend volume CLIQ input for test.

            input = "modifyVolume description="fake description"
                                  volumeName=fakevolume
                                  output=XML size=2GB"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['size'], '2GB')
            return output, None

        def assign_volume(cliq_args):
            """Assign volume CLIQ input for test.

            input = "assignVolumeToServer volumeName=fakevolume
                                          serverName=fakehost
                                          output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="174" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['serverName'],
                             self.connector['host'])
            return output, None

        def unassign_volume(cliq_args):
            """Unassign volume CLIQ input for test.

            input = "unassignVolumeToServer volumeName=fakevolume
                                            serverName=fakehost output=XML
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="205" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            self.assertEqual(cliq_args['serverName'],
                             self.connector['host'])
            return output, None

        def create_snapshot(cliq_args):
            """Create snapshot CLIQ input for test.

            input = "createSnapshot description="fake description"
                                    snapshotName=fakesnapshot
                                    volumeName=fakevolume
                                    output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['snapshotName'], self.snapshot_name)
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            return output, None

        def delete_snapshot(cliq_args):
            """Delete shapshot CLIQ input for test.

            input = "deleteSnapshot snapshotName=fakesnapshot prompt=false
                                    output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="164" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['snapshotName'], self.snapshot_name)
            self.assertEqual(cliq_args['prompt'], 'false')
            return output, None

        def create_volume_from_snapshot(cliq_args):
            """Create volume from snapshot CLIQ input for test.

            input = "cloneSnapshot description="fake description"
                                   snapshotName=fakesnapshot
                                   volumeName=fakevolume
                                   output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded."
                          name="CliqSuccess" processingTime="181" result="0"/>
                </gauche>"""
            self.assertEqual(cliq_args['snapshotName'], self.snapshot_name)
            self.assertEqual(cliq_args['volumeName'], self.volume_name)
            return output, None

        def get_cluster_info(cliq_args):
            """Get cluster info CLIQ input for test.

            input = "getClusterInfo clusterName=Cluster01 searchDepth=1
                                    verbose=0 output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded." name="CliqSuccess"
                          processingTime="1164" result="0">
                <cluster blockSize="1024" description=""
                         maxVolumeSizeReplication1="622957690"
                         maxVolumeSizeReplication2="311480287"
                         minVolumeSize="262144" name="Cluster01"
                         pageSize="262144" spaceTotal="633697992"
                         storageNodeCount="2" unprovisionedSpace="622960574"
                         useVip="true">
                <nsm ipAddress="10.0.1.7" name="111-vsa"/>
                <nsm ipAddress="10.0.1.8" name="112-vsa"/>
                <vip ipAddress="10.0.1.6" subnetMask="255.255.255.0"/>
                </cluster></response></gauche>"""
            return output, None

        def get_volume_info(cliq_args):
            """Get volume info CLIQ input for test.

            input = "getVolumeInfo volumeName=fakevolume output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded." name="CliqSuccess"
                          processingTime="87" result="0">
                <volume autogrowPages="4" availability="online"
                        blockSize="1024" bytesWritten="0" checkSum="false"
                        clusterName="Cluster01" created="2011-02-08T19:56:53Z"
                        deleting="false" description="" groupName="Group01"
                        initialQuota="536870912" isPrimary="true"
                iscsiIqn="iqn.2003-10.com.lefthandnetworks:group01:25366:fakev"
                maxSize="6865387257856" md5="9fa5c8b2cca54b2948a63d833097e1ca"
                minReplication="1" name="vol-b" parity="0" replication="2"
                reserveQuota="536870912" scratchQuota="4194304"
                serialNumber="9fa5c8b2cca54b2948a63d8"
                size="1073741824" stridePages="32" thinProvision="true">
                <status description="OK" value="2"/>
                <permission access="rw" authGroup="api-1"
                            chapName="chapusername" chapRequired="true"
                            id="25369" initiatorSecret="" iqn=""
                            iscsiEnabled="true" loadBalance="true"
                            targetSecret="supersecret"/>
                </volume></response></gauche>"""
            return output, None

        def get_snapshot_info(cliq_args):
            """Get snapshot info CLIQ input for test.

            input = "getSnapshotInfo snapshotName=fakesnapshot output=XML"
            """
            output = """<gauche version="1.0">
                <response description="Operation succeeded." name="CliqSuccess"
                          processingTime="87" result="0">
                <snapshot applicationManaged="false" autogrowPages="32768"
                    automatic="false" availability="online" bytesWritten="0"
                    clusterName="CloudCluster1" created="2013-08-26T07:03:44Z"
                    deleting="false" description="" groupName="CloudGroup1"
                    id="730" initialQuota="536870912" isPrimary="true"
                    iscsiIqn="iqn.2003-10.com.lefthandnetworks:cloudgroup1:73"
                    md5="a64b4f850539c07fb5ce3cee5db1fcce" minReplication="1"
                    name="snapshot-7849288e-e5e8-42cb-9687-9af5355d674b"
                    replication="2" reserveQuota="536870912" scheduleId="0"
                    scratchQuota="4194304" scratchWritten="0"
                    serialNumber="a64b4f850539c07fb5ce3cee5db1fcce"
                    size="2147483648" stridePages="32"
                    volumeSerial="a64b4f850539c07fb5ce3cee5db1fcce">
               <status description="OK" value="2"/>
               <permission access="rw"
                     authGroup="api-34281B815713B78-(trimmed)51ADD4B7030853AA7"
                     chapName="chapusername" chapRequired="true" id="25369"
                     initiatorSecret="" iqn="" iscsiEnabled="true"
                     loadBalance="true" targetSecret="supersecret"/>
               </snapshot></response></gauche>"""
            return output, None

        def get_server_info(cliq_args):
            """Get server info CLIQ input for test.

            input = "getServerInfo serverName=fakeName"
            """
            output = """<gauche version="1.0"><response result="0"/>
                     </gauche>"""
            return output, None

        def create_server(cliq_args):
            """Create server CLIQ input for test.

            input = "createServer serverName=fakeName initiator=something"
            """
            output = """<gauche version="1.0"><response result="0"/>
                     </gauche>"""
            return output, None

        def test_error(cliq_args):
            output = """<gauche version="1.0">
                <response description="Volume '134234' not found."
                name="CliqVolumeNotFound" processingTime="1083"
                result="8000100c"/>
                </gauche>"""
            return output, None

        def test_paramiko_1_13_0(cliq_args):

            # paramiko 1.13.0 now returns unicode
            output = unicode(
                '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
                '<gauche version="1.0">\n\n  <response description="Operation'
                ' succeeded." name="CliqSuccess" processingTime="423" '
                'result="0">\n    <cluster adaptiveOptimization="false" '
                'blockSize="1024" description="" maxVolumeSizeReplication1='
                '"114594676736" minVolumeSize="262144" name="clusterdemo" '
                'pageSize="262144" spaceTotal="118889644032" storageNodeCount='
                '"1" unprovisionedSpace="114594676736" useVip="true">\n'
                '      <nsm ipAddress="10.10.29.102" name="lefdemo1"/>\n'
                '      <vip ipAddress="10.10.22.87" subnetMask='
                '"255.255.224.0"/>\n    </cluster>\n  </response>\n\n'
                '</gauche>\n    ')
            return output, None

        def test_paramiko_1_10_0(cliq_args):

            # paramiko 1.10.0 returns python default encoding.
            output = (
                '<?xml version="1.0" encoding="UTF-8" standalone="no" ?>\n'
                '<gauche version="1.0">\n\n  <response description="Operation'
                ' succeeded." name="CliqSuccess" processingTime="423" '
                'result="0">\n    <cluster adaptiveOptimization="false" '
                'blockSize="1024" description="" maxVolumeSizeReplication1='
                '"114594676736" minVolumeSize="262144" name="clusterdemo" '
                'pageSize="262144" spaceTotal="118889644032" storageNodeCount='
                '"1" unprovisionedSpace="114594676736" useVip="true">\n'
                '      <nsm ipAddress="10.10.29.102" name="lefdemo1"/>\n'
                '      <vip ipAddress="10.10.22.87" subnetMask='
                '"255.255.224.0"/>\n    </cluster>\n  </response>\n\n'
                '</gauche>\n    ')
            return output, None

        self.assertEqual(cliq_args['output'], 'XML')
        try:
            verbs = {'createVolume': create_volume,
                     'deleteVolume': delete_volume,
                     'modifyVolume': extend_volume,
                     'assignVolumeToServer': assign_volume,
                     'unassignVolumeToServer': unassign_volume,
                     'createSnapshot': create_snapshot,
                     'deleteSnapshot': delete_snapshot,
                     'cloneSnapshot': create_volume_from_snapshot,
                     'getClusterInfo': get_cluster_info,
                     'getVolumeInfo': get_volume_info,
                     'getSnapshotInfo': get_snapshot_info,
                     'getServerInfo': get_server_info,
                     'createServer': create_server,
                     'testError': test_error,
                     'testParamiko_1.10.1': test_paramiko_1_10_0,
                     'testParamiko_1.13.1': test_paramiko_1_13_0}
        except KeyError:
            raise NotImplementedError()

        return verbs[verb](cliq_args)

    def setUp(self):
        super(TestHPLeftHandCLIQISCSIDriver, self).setUp()

        self.properties = {
            'target_discoverd': True,
            'target_portal': '10.0.1.6:3260',
            'target_iqn':
            'iqn.2003-10.com.lefthandnetworks:group01:25366:fakev',
            'volume_id': self.volume_id}

    def tearDown(self):
        super(TestHPLeftHandCLIQISCSIDriver, self).tearDown()

    def default_mock_conf(self):

        mock_conf = mock.Mock()
        mock_conf.san_ip = '10.10.10.10'
        mock_conf.san_login = 'foo'
        mock_conf.san_password = 'bar'
        mock_conf.san_ssh_port = 16022
        mock_conf.san_clustername = 'CloudCluster1'
        mock_conf.hplefthand_api_url = None
        return mock_conf

    def setup_driver(self, config=None):

        if config is None:
            config = self.default_mock_conf()

        self.driver = hp_lefthand_iscsi.HPLeftHandISCSIDriver(
            configuration=config)
        self.driver.do_setup(None)

        self.driver.proxy._cliq_run = mock.Mock(
            side_effect=self._fake_cliq_run)
        return self.driver.proxy._cliq_run

    def test_create_volume(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        volume = {'name': self.volume_name, 'size': 1}
        model_update = self.driver.create_volume(volume)
        expected_iqn = "iqn.2003-10.com.lefthandnetworks:group01:25366:fakev 0"
        expected_location = "10.0.1.6:3260,1 %s" % expected_iqn
        self.assertEqual(model_update['provider_location'], expected_location)

        expected = [
            mock.call(
                'createVolume', {
                    'clusterName': 'CloudCluster1',
                    'volumeName': 'fakevolume',
                    'thinProvision': '1',
                    'output': 'XML',
                    'size': '1GB'},
                True),
            mock.call(
                'getVolumeInfo', {
                    'volumeName': 'fakevolume',
                    'output': 'XML'},
                True),
            mock.call(
                'getClusterInfo', {
                    'clusterName': 'Cluster01',
                    'searchDepth': '1',
                    'verbose': '0',
                    'output': 'XML'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_delete_volume(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        volume = {'name': self.volume_name}
        self.driver.delete_volume(volume)

        expected = [
            mock.call(
                'getVolumeInfo', {
                    'volumeName': 'fakevolume',
                    'output': 'XML'},
                True),
            mock.call(
                'deleteVolume', {
                    'volumeName': 'fakevolume',
                    'prompt': 'false',
                    'output': 'XML'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_extend_volume(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        volume = {'name': self.volume_name}
        self.driver.extend_volume(volume, 2)

        expected = [
            mock.call(
                'modifyVolume', {
                    'volumeName': 'fakevolume',
                    'output': 'XML',
                    'size': '2GB'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_initialize_connection(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        self.driver.proxy._get_iscsi_properties = mock.Mock(
            return_value=self.properties)
        volume = {'name': self.volume_name}
        result = self.driver.initialize_connection(volume,
                                                   self.connector)
        self.assertEqual(result['driver_volume_type'], 'iscsi')
        self.assertDictMatch(result['data'], self.properties)

        expected = [
            mock.call(
                'getServerInfo', {
                    'output': 'XML',
                    'serverName': 'fakehost'},
                False),
            mock.call(
                'assignVolumeToServer', {
                    'volumeName': 'fakevolume',
                    'serverName': 'fakehost',
                    'output': 'XML'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_terminate_connection(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        volume = {'name': self.volume_name}
        self.driver.terminate_connection(volume, self.connector)

        expected = [
            mock.call(
                'unassignVolumeToServer', {
                    'volumeName': 'fakevolume',
                    'serverName': 'fakehost',
                    'output': 'XML'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_create_snapshot(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        snapshot = {'name': self.snapshot_name,
                    'volume_name': self.volume_name}
        self.driver.create_snapshot(snapshot)

        expected = [
            mock.call(
                'createSnapshot', {
                    'snapshotName': 'fakeshapshot',
                    'output': 'XML',
                    'inheritAccess': 1,
                    'volumeName': 'fakevolume'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_delete_snapshot(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        snapshot = {'name': self.snapshot_name}
        self.driver.delete_snapshot(snapshot)

        expected = [
            mock.call(
                'getSnapshotInfo', {
                    'snapshotName': 'fakeshapshot',
                    'output': 'XML'},
                True),
            mock.call(
                'deleteSnapshot', {
                    'snapshotName': 'fakeshapshot',
                    'prompt': 'false',
                    'output': 'XML'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_create_volume_from_snapshot(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()

        volume = {'name': self.volume_name}
        snapshot = {'name': self.snapshot_name}
        model_update = self.driver.create_volume_from_snapshot(volume,
                                                               snapshot)
        expected_iqn = "iqn.2003-10.com.lefthandnetworks:group01:25366:fakev 0"
        expected_location = "10.0.1.6:3260,1 %s" % expected_iqn
        self.assertEqual(model_update['provider_location'], expected_location)

        expected = [
            mock.call(
                'cloneSnapshot', {
                    'snapshotName': 'fakeshapshot',
                    'output': 'XML',
                    'volumeName': 'fakevolume'},
                True),
            mock.call(
                'getVolumeInfo', {
                    'volumeName': 'fakevolume',
                    'output': 'XML'},
                True),
            mock.call(
                'getClusterInfo', {
                    'clusterName': 'Cluster01',
                    'searchDepth': '1',
                    'verbose': '0',
                    'output': 'XML'},
                True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_get_volume_stats(self):

        # set up driver with default config
        mock_cliq_run = self.setup_driver()
        volume_stats = self.driver.get_volume_stats(True)

        self.assertEqual(volume_stats['vendor_name'], 'Hewlett-Packard')
        self.assertEqual(volume_stats['storage_protocol'], 'iSCSI')

        expected = [
            mock.call('getClusterInfo', {
                'searchDepth': 1,
                'clusterName': 'CloudCluster1',
                'output': 'XML'}, True)]

        # validate call chain
        mock_cliq_run.assert_has_calls(expected)

    def test_cliq_run_xml_paramiko_1_13_0(self):

        # set up driver with default config
        self.setup_driver()
        xml = self.driver.proxy._cliq_run_xml('testParamiko_1.13.1', {})
        self.assertIsNotNone(xml)

    def test_cliq_run_xml_paramiko_1_10_0(self):

        # set up driver with default config
        self.setup_driver()
        xml = self.driver.proxy._cliq_run_xml('testParamiko_1.10.1', {})
        self.assertIsNotNone(xml)


class TestHPLeftHandRESTISCSIDriver(HPLeftHandBaseDriver, test.TestCase):

    driver_startup_call_stack = [
        mock.call.login('foo1', 'bar2'),
        mock.call.getClusterByName('CloudCluster1'),
        mock.call.getCluster(1)]

    def setUp(self):
        super(TestHPLeftHandRESTISCSIDriver, self).setUp()

    def tearDown(self):
        super(TestHPLeftHandRESTISCSIDriver, self).tearDown()

    def default_mock_conf(self):

        mock_conf = mock.Mock()
        mock_conf.hplefthand_api_url = 'http://fake.foo:8080/lhos'
        mock_conf.hplefthand_username = 'foo1'
        mock_conf.hplefthand_password = 'bar2'
        mock_conf.hplefthand_iscsi_chap_enabled = False
        mock_conf.hplefthand_debug = False
        mock_conf.hplefthand_clustername = "CloudCluster1"
        return mock_conf

    @mock.patch('hplefthandclient.client.HPLeftHandClient', spec=True)
    def setup_driver(self, _mock_client, config=None):

        if config is None:
            config = self.default_mock_conf()

        _mock_client.return_value.getClusterByName.return_value = {
            'id': 1, 'virtualIPAddresses': [{'ipV4Address': '10.0.1.6'}]}
        _mock_client.return_value.getCluster.return_value = {
            'spaceTotal': units.GiB * 500,
            'spaceAvailable': units.GiB * 250}
        self.driver = hp_lefthand_iscsi.HPLeftHandISCSIDriver(
            configuration=config)
        self.driver.do_setup(None)
        return _mock_client.return_value

    def test_create_volume(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        # mock return value of createVolume
        mock_client.createVolume.return_value = {
            'iscsiIqn': self.connector['initiator']}

        # execute driver
        volume_info = self.driver.create_volume(self.volume)

        self.assertEqual('10.0.1.6:3260,1 iqn.1993-08.org.debian:01:222 0',
                         volume_info['provider_location'])

        expected = self.driver_startup_call_stack + [
            mock.call.createVolume(
                'fakevolume',
                1,
                units.GiB,
                {'isThinProvisioned': True, 'clusterName': 'CloudCluster1'})]

        mock_client.assert_has_calls(expected)

        # mock HTTPServerError
        mock_client.createVolume.side_effect = hpexceptions.HTTPServerError()
        # ensure the raised exception is a cinder exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.create_volume, self.volume)

    @mock.patch.object(
        volume_types,
        'get_volume_type',
        return_value={'extra_specs': {'hplh:provisioning': 'full'}})
    def test_create_volume_with_es(self, _mock_volume_type):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        volume_with_vt = self.volume
        volume_with_vt['volume_type_id'] = 1

        # mock return value of createVolume
        mock_client.createVolume.return_value = {
            'iscsiIqn': self.connector['initiator']}

        # execute creat_volume
        volume_info = self.driver.create_volume(volume_with_vt)

        self.assertEqual('10.0.1.6:3260,1 iqn.1993-08.org.debian:01:222 0',
                         volume_info['provider_location'])

        expected = self.driver_startup_call_stack + [
            mock.call.createVolume(
                'fakevolume',
                1,
                units.GiB,
                {'isThinProvisioned': False, 'clusterName': 'CloudCluster1'})]

        mock_client.assert_has_calls(expected)

    def test_delete_volume(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        # mock return value of getVolumeByName
        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        # execute delete_volume
        self.driver.delete_volume(self.volume)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.deleteVolume(self.volume_id)]

        mock_client.assert_has_calls(expected)

        # mock HTTPNotFound (volume not found)
        mock_client.getVolumeByName.side_effect = hpexceptions.HTTPNotFound()
        # no exception should escape method
        self.driver.delete_volume(self.volume)

        # mock HTTPConflict
        mock_client.deleteVolume.side_effect = hpexceptions.HTTPConflict()
        # ensure the raised exception is a cinder exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.delete_volume, self.volume_id)

    def test_extend_volume(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        # mock return value of getVolumeByName
        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        # execute extend_volume
        self.driver.extend_volume(self.volume, 2)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.modifyVolume(1, {'size': 2 * units.GiB})]

        # validate call chain
        mock_client.assert_has_calls(expected)

        # mock HTTPServerError (array failure)
        mock_client.modifyVolume.side_effect = hpexceptions.HTTPServerError()
        # ensure the raised exception is a cinder exception
        self.assertRaises(exception.VolumeBackendAPIException,
                          self.driver.extend_volume, self.volume, 2)

    def test_initialize_connection(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        # mock return value of getVolumeByName
        mock_client.getServerByName.side_effect = hpexceptions.HTTPNotFound()
        mock_client.createServer.return_value = {'id': self.server_id}
        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        # execute initialize_connection
        result = self.driver.initialize_connection(
            self.volume,
            self.connector)

        # validate
        self.assertEqual(result['driver_volume_type'], 'iscsi')
        self.assertEqual(result['data']['target_discovered'], False)
        self.assertEqual(result['data']['volume_id'], self.volume_id)
        self.assertTrue('auth_method' not in result['data'])

        expected = self.driver_startup_call_stack + [
            mock.call.getServerByName('fakehost'),
            mock.call.createServer
            (
                'fakehost',
                'iqn.1993-08.org.debian:01:222',
                None
            ),
            mock.call.getVolumeByName('fakevolume'),
            mock.call.addServerAccess(1, 0)]

        # validate call chain
        mock_client.assert_has_calls(expected)

        # mock HTTPServerError (array failure)
        mock_client.createServer.side_effect = hpexceptions.HTTPServerError()
        # ensure the raised exception is a cinder exception
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.initialize_connection, self.volume, self.connector)

    def test_initialize_connection_with_chaps(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        # mock return value of getVolumeByName
        mock_client.getServerByName.side_effect = hpexceptions.HTTPNotFound()
        mock_client.createServer.return_value = {
            'id': self.server_id,
            'chapAuthenticationRequired': True,
            'chapTargetSecret': 'dont_tell'}
        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        # execute initialize_connection
        result = self.driver.initialize_connection(
            self.volume,
            self.connector)

        # validate
        self.assertEqual(result['driver_volume_type'], 'iscsi')
        self.assertEqual(result['data']['target_discovered'], False)
        self.assertEqual(result['data']['volume_id'], self.volume_id)
        self.assertEqual(result['data']['auth_method'], 'CHAP')

        expected = self.driver_startup_call_stack + [
            mock.call.getServerByName('fakehost'),
            mock.call.createServer
            (
                'fakehost',
                'iqn.1993-08.org.debian:01:222',
                None
            ),
            mock.call.getVolumeByName('fakevolume'),
            mock.call.addServerAccess(1, 0)]

        # validate call chain
        mock_client.assert_has_calls(expected)

    def test_terminate_connection(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        mock_client.getVolumeByName.return_value = {'id': self.volume_id}
        mock_client.getServerByName.return_value = {'id': self.server_id}

        # execute terminate_connection
        self.driver.terminate_connection(self.volume, self.connector)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.getServerByName('fakehost'),
            mock.call.removeServerAccess(1, 0)]

        # validate call chain
        mock_client.assert_has_calls(expected)

        mock_client.getVolumeByName.side_effect = hpexceptions.HTTPNotFound()
        # ensure the raised exception is a cinder exception
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.terminate_connection,
            self.volume,
            self.connector)

    def test_create_snapshot(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        # execute create_snapshot
        self.driver.create_snapshot(self.snapshot)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.createSnapshot(
                'fakeshapshot',
                1,
                {'inheritAccess': True})]

        # validate call chain
        mock_client.assert_has_calls(expected)

        # mock HTTPServerError (array failure)
        mock_client.getVolumeByName.side_effect = hpexceptions.HTTPNotFound()
        # ensure the raised exception is a cinder exception
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.create_snapshot, self.snapshot)

    def test_delete_snapshot(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        mock_client.getSnapshotByName.return_value = {'id': self.snapshot_id}

        # execute delete_snapshot
        self.driver.delete_snapshot(self.snapshot)

        expected = self.driver_startup_call_stack + [
            mock.call.getSnapshotByName('fakeshapshot'),
            mock.call.deleteSnapshot(3)]

        # validate call chain
        mock_client.assert_has_calls(expected)

        mock_client.getSnapshotByName.side_effect = hpexceptions.HTTPNotFound()
        # no exception is thrown, just error msg is logged
        self.driver.delete_snapshot(self.snapshot)

        # mock HTTPServerError (array failure)
        ex = hpexceptions.HTTPServerError({'message': 'Some message.'})
        mock_client.getSnapshotByName.side_effect = ex
        # ensure the raised exception is a cinder exception
        self.assertRaises(
            exception.VolumeBackendAPIException,
            self.driver.delete_snapshot,
            self.snapshot)

        # mock HTTPServerError because the snap is in use
        ex = hpexceptions.HTTPServerError({
            'message':
            'Hey, dude cannot be deleted because it is a clone point duh.'})
        mock_client.getSnapshotByName.side_effect = ex
        # ensure the raised exception is a cinder exception
        self.assertRaises(
            exception.SnapshotIsBusy,
            self.driver.delete_snapshot,
            self.snapshot)

    def test_create_volume_from_snapshot(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        mock_client.getSnapshotByName.return_value = {'id': self.snapshot_id}
        mock_client.cloneSnapshot.return_value = {
            'iscsiIqn': self.connector['initiator']}

        # execute create_volume_from_snapshot
        model_update = self.driver.create_volume_from_snapshot(
            self.volume, self.snapshot)

        expected_iqn = 'iqn.1993-08.org.debian:01:222 0'
        expected_location = "10.0.1.6:3260,1 %s" % expected_iqn
        self.assertEqual(model_update['provider_location'], expected_location)

        expected = self.driver_startup_call_stack + [
            mock.call.getSnapshotByName('fakeshapshot'),
            mock.call.cloneSnapshot('fakevolume', 3)]

        # validate call chain
        mock_client.assert_has_calls(expected)

    def test_create_cloned_volume(self):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        # execute create_cloned_volume
        self.driver.create_cloned_volume(
            self.cloned_volume, self.volume)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.cloneVolume('clone_volume', 1)]

        # validate call chain
        mock_client.assert_has_calls(expected)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_extra_spec_mapping(self, _mock_get_volume_type):

        # setup drive with default configuration
        self.setup_driver()

        # 2 extra specs we don't care about, and
        # 1 that will get mapped
        _mock_get_volume_type.return_value = {
            'extra_specs': {
                'foo:bar': 'fake',
                'bar:foo': 1234,
                'hplh:provisioning': 'full'}}

        volume_with_vt = self.volume
        volume_with_vt['volume_type_id'] = self.volume_type_id

        # get the extra specs of interest from this volume's volume type
        volume_extra_specs = self.driver.proxy._get_volume_extra_specs(
            volume_with_vt)
        extra_specs = self.driver.proxy._get_lh_extra_specs(
            volume_extra_specs,
            hp_lefthand_rest_proxy.extra_specs_key_map.keys())

        # map the extra specs key/value pairs to key/value pairs
        # used as optional configuration values by the LeftHand backend
        optional = self.driver.proxy._map_extra_specs(extra_specs)

        self.assertDictMatch({'isThinProvisioned': False}, optional)

    @mock.patch.object(volume_types, 'get_volume_type')
    def test_extra_spec_mapping_invalid_value(self, _mock_get_volume_type):

        # setup drive with default configuration
        self.setup_driver()

        volume_with_vt = self.volume
        volume_with_vt['volume_type_id'] = self.volume_type_id

        _mock_get_volume_type.return_value = {
            'extra_specs': {
                # r-07 is an invalid value for hplh:ao
                'hplh:data_pl': 'r-07',
                'hplh:ao': 'true'}}

        # get the extra specs of interest from this volume's volume type
        volume_extra_specs = self.driver.proxy._get_volume_extra_specs(
            volume_with_vt)
        extra_specs = self.driver.proxy._get_lh_extra_specs(
            volume_extra_specs,
            hp_lefthand_rest_proxy.extra_specs_key_map.keys())

        # map the extra specs key/value pairs to key/value pairs
        # used as optional configuration values by the LeftHand backend
        optional = self.driver.proxy._map_extra_specs(extra_specs)

        # {'hplh:ao': 'true'} should map to
        # {'isAdaptiveOptimizationEnabled': True}
        # without hplh:data_pl since r-07 is an invalid value
        self.assertDictMatch({'isAdaptiveOptimizationEnabled': True}, optional)

    def test_retype_with_no_LH_extra_specs(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        ctxt = context.get_admin_context()

        host = {'host': self.serverName}
        key_specs_old = {'foo': False, 'bar': 2, 'error': True}
        key_specs_new = {'foo': True, 'bar': 5, 'error': False}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, equal = volume_types.volume_types_diff(ctxt, old_type_ref['id'],
                                                     new_type_ref['id'])

        volume = dict.copy(self.volume)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.retype(ctxt, volume, new_type, diff, host)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume')]

        # validate call chain
        mock_client.assert_has_calls(expected)

    def test_retype_with_only_LH_extra_specs(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()
        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        ctxt = context.get_admin_context()

        host = {'host': self.serverName}
        key_specs_old = {'hplh:provisioning': 'thin'}
        key_specs_new = {'hplh:provisioning': 'full', 'hplh:ao': 'true'}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, equal = volume_types.volume_types_diff(ctxt, old_type_ref['id'],
                                                     new_type_ref['id'])

        volume = dict.copy(self.volume)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.retype(ctxt, volume, new_type, diff, host)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.modifyVolume(
                1, {
                    'isThinProvisioned': False,
                    'isAdaptiveOptimizationEnabled': True})]

        # validate call chain
        mock_client.assert_has_calls(expected)

    def test_retype_with_both_extra_specs(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()
        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        ctxt = context.get_admin_context()

        host = {'host': self.serverName}
        key_specs_old = {'hplh:provisioning': 'full', 'foo': 'bar'}
        key_specs_new = {'hplh:provisioning': 'thin', 'foo': 'foobar'}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, equal = volume_types.volume_types_diff(ctxt, old_type_ref['id'],
                                                     new_type_ref['id'])

        volume = dict.copy(self.volume)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.retype(ctxt, volume, new_type, diff, host)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.modifyVolume(1, {'isThinProvisioned': True})]

        # validate call chain
        mock_client.assert_has_calls(expected)

    def test_retype_same_extra_specs(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()
        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        ctxt = context.get_admin_context()

        host = {'host': self.serverName}
        key_specs_old = {'hplh:provisioning': 'full', 'hplh:ao': 'true'}
        key_specs_new = {'hplh:provisioning': 'full', 'hplh:ao': 'false'}
        old_type_ref = volume_types.create(ctxt, 'old', key_specs_old)
        new_type_ref = volume_types.create(ctxt, 'new', key_specs_new)

        diff, equal = volume_types.volume_types_diff(ctxt, old_type_ref['id'],
                                                     new_type_ref['id'])

        volume = dict.copy(self.volume)
        old_type = volume_types.get_volume_type(ctxt, old_type_ref['id'])
        volume['volume_type'] = old_type
        volume['host'] = host
        new_type = volume_types.get_volume_type(ctxt, new_type_ref['id'])

        self.driver.retype(ctxt, volume, new_type, diff, host)

        expected = self.driver_startup_call_stack + [
            mock.call.getVolumeByName('fakevolume'),
            mock.call.modifyVolume(
                1,
                {'isAdaptiveOptimizationEnabled': False})]

        # validate call chain
        mock_client.assert_has_calls(expected)

    def test_migrate_no_location(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        host = {'host': self.serverName, 'capabilities': {}}
        (migrated, update) = self.driver.migrate_volume(
            None,
            self.volume,
            host)
        self.assertFalse(migrated)

        # only startup code is called
        mock_client.assert_has_calls(self.driver_startup_call_stack)
        # and nothing else
        self.assertEqual(
            len(self.driver_startup_call_stack),
            len(mock_client.method_calls))

    def test_migrate_incorrect_vip(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()
        mock_client.getClusterByName.return_value = {
            "virtualIPAddresses": [{
                "ipV4Address": "10.10.10.10",
                "ipV4NetMask": "255.255.240.0"}]}

        mock_client.getVolumeByName.return_value = {'id': self.volume_id}

        location = (self.driver.proxy.DRIVER_LOCATION % {
            'cluster': 'New_CloudCluster',
            'vip': '10.10.10.111'})

        host = {
            'host': self.serverName,
            'capabilities': {'location_info': location}}
        (migrated, update) = self.driver.migrate_volume(
            None,
            self.volume,
            host)
        self.assertFalse(migrated)

        expected = self.driver_startup_call_stack + [
            mock.call.getClusterByName('New_CloudCluster')]

        mock_client.assert_has_calls(expected)
        # and nothing else
        self.assertEqual(
            len(expected),
            len(mock_client.method_calls))

    def test_migrate_with_location(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()
        mock_client.getClusterByName.return_value = {
            "virtualIPAddresses": [{
                "ipV4Address": "10.10.10.111",
                "ipV4NetMask": "255.255.240.0"}]}

        mock_client.getVolumeByName.return_value = {'id': self.volume_id,
                                                    'iscsiSessions': None}
        mock_client.getVolume.return_value = {'snapshots': {
            'resource': None}}

        location = (self.driver.proxy.DRIVER_LOCATION % {
            'cluster': 'New_CloudCluster',
            'vip': '10.10.10.111'})

        host = {
            'host': self.serverName,
            'capabilities': {'location_info': location}}
        (migrated, update) = self.driver.migrate_volume(
            None,
            self.volume,
            host)
        self.assertTrue(migrated)

        expected = self.driver_startup_call_stack + [
            mock.call.getClusterByName('New_CloudCluster'),
            mock.call.getVolumeByName('fakevolume'),
            mock.call.getVolume(
                1,
                'fields=snapshots,snapshots[resource[members[name]]]'),
            mock.call.modifyVolume(1, {'clusterName': 'New_CloudCluster'})]

        mock_client.assert_has_calls(expected)
        # and nothing else
        self.assertEqual(
            len(expected),
            len(mock_client.method_calls))

    def test_migrate_with_Snapshots(self):
        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()
        mock_client.getClusterByName.return_value = {
            "virtualIPAddresses": [{
                "ipV4Address": "10.10.10.111",
                "ipV4NetMask": "255.255.240.0"}]}

        mock_client.getVolumeByName.return_value = {
            'id': self.volume_id,
            'iscsiSessions': None}
        mock_client.getVolume.return_value = {'snapshots': {
            'resource': 'snapfoo'}}

        location = (self.driver.proxy.DRIVER_LOCATION % {
            'cluster': 'New_CloudCluster',
            'vip': '10.10.10.111'})

        host = {
            'host': self.serverName,
            'capabilities': {'location_info': location}}
        (migrated, update) = self.driver.migrate_volume(
            None,
            self.volume,
            host)
        self.assertFalse(migrated)

        expected = self.driver_startup_call_stack + [
            mock.call.getClusterByName('New_CloudCluster'),
            mock.call.getVolumeByName('fakevolume'),
            mock.call.getVolume(
                1,
                'fields=snapshots,snapshots[resource[members[name]]]')]

        mock_client.assert_has_calls(expected)
        # and nothing else
        self.assertEqual(
            len(expected),
            len(mock_client.method_calls))

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'extra_specs': {'hplh:ao': 'true'}})
    def test_create_volume_with_ao_true(self, _mock_volume_type):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        volume_with_vt = self.volume
        volume_with_vt['volume_type_id'] = 1

        # mock return value of createVolume
        mock_client.createVolume.return_value = {
            'iscsiIqn': self.connector['initiator']}

        volume_info = self.driver.create_volume(volume_with_vt)

        self.assertEqual('10.0.1.6:3260,1 iqn.1993-08.org.debian:01:222 0',
                         volume_info['provider_location'])

        # make sure createVolume is called without
        # isAdaptiveOptimizationEnabled == true
        expected = self.driver_startup_call_stack + [
            mock.call.createVolume(
                'fakevolume',
                1,
                units.GiB,
                {'isThinProvisioned': True, 'clusterName': 'CloudCluster1'})]

        mock_client.assert_has_calls(expected)

    @mock.patch.object(volume_types, 'get_volume_type',
                       return_value={'extra_specs': {'hplh:ao': 'false'}})
    def test_create_volume_with_ao_false(self, _mock_volume_type):

        # setup drive with default configuration
        # and return the mock HTTP LeftHand client
        mock_client = self.setup_driver()

        volume_with_vt = self.volume
        volume_with_vt['volume_type_id'] = 1

        # mock return value of createVolume
        mock_client.createVolume.return_value = {
            'iscsiIqn': self.connector['initiator']}

        volume_info = self.driver.create_volume(volume_with_vt)

        self.assertEqual('10.0.1.6:3260,1 iqn.1993-08.org.debian:01:222 0',
                         volume_info['provider_location'])

        # make sure createVolume is called with
        # isAdaptiveOptimizationEnabled == false
        expected = self.driver_startup_call_stack + [
            mock.call.createVolume(
                'fakevolume',
                1,
                units.GiB,
                {'isThinProvisioned': True,
                 'clusterName': 'CloudCluster1',
                 'isAdaptiveOptimizationEnabled': False})]

        mock_client.assert_has_calls(expected)
