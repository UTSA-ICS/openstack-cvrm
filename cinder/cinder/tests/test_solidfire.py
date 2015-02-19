
# Copyright 2012 OpenStack Foundation
# All Rights Reserved.
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

import mox

from cinder import context
from cinder import exception
from cinder.openstack.common import log as logging
from cinder.openstack.common import timeutils
from cinder import test
from cinder import units
from cinder.volume import configuration as conf
from cinder.volume.drivers.solidfire import SolidFireDriver
from cinder.volume import qos_specs
from cinder.volume import volume_types

LOG = logging.getLogger(__name__)


def create_configuration():
    configuration = mox.MockObject(conf.Configuration)
    configuration.san_is_local = False
    configuration.append_config_values(mox.IgnoreArg())
    return configuration


class SolidFireVolumeTestCase(test.TestCase):
    def setUp(self):
        self.ctxt = context.get_admin_context()
        self._mox = mox.Mox()
        self.configuration = mox.MockObject(conf.Configuration)
        self.configuration.sf_allow_tenant_qos = True
        self.configuration.san_is_local = True
        self.configuration.sf_emulate_512 = True
        self.configuration.sf_account_prefix = 'cinder'

        super(SolidFireVolumeTestCase, self).setUp()
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)

        self.expected_qos_results = {'minIOPS': 1000,
                                     'maxIOPS': 10000,
                                     'burstIOPS': 20000}

    def fake_issue_api_request(obj, method, params, version='1.0'):
        if method is 'GetClusterCapacity' and version == '1.0':
            LOG.info('Called Fake GetClusterCapacity...')
            data = {'result':
                    {'clusterCapacity': {'maxProvisionedSpace': 99999999,
                     'usedSpace': 999,
                     'compressionPercent': 100,
                     'deDuplicationPercent': 100,
                     'thinProvisioningPercent': 100}}}
            return data

        elif method is 'GetClusterInfo' and version == '1.0':
            LOG.info('Called Fake GetClusterInfo...')
            results = {'result': {'clusterInfo':
                                  {'name': 'fake-cluster',
                                   'mvip': '1.1.1.1',
                                   'svip': '1.1.1.1',
                                   'uniqueID': 'unqid',
                                   'repCount': 2,
                                   'attributes': {}}}}
            return results

        elif method is 'AddAccount' and version == '1.0':
            LOG.info('Called Fake AddAccount...')
            return {'result': {'accountID': 25}, 'id': 1}

        elif method is 'GetAccountByName' and version == '1.0':
            LOG.info('Called Fake GetAccountByName...')
            results = {'result': {'account':
                                  {'accountID': 25,
                                   'username': params['username'],
                                   'status': 'active',
                                   'initiatorSecret': '123456789012',
                                   'targetSecret': '123456789012',
                                   'attributes': {},
                                   'volumes': [6, 7, 20]}},
                       "id": 1}
            return results

        elif method is 'CreateVolume' and version == '1.0':
            LOG.info('Called Fake CreateVolume...')
            return {'result': {'volumeID': 5}, 'id': 1}

        elif method is 'DeleteVolume' and version == '1.0':
            LOG.info('Called Fake DeleteVolume...')
            return {'result': {}, 'id': 1}

        elif method is 'ModifyVolume' and version == '5.0':
            LOG.info('Called Fake ModifyVolume...')
            return {'result': {}, 'id': 1}

        elif method is 'CloneVolume':
            return {'result': {'volumeID': 6}, 'id': 2}

        elif method is 'ModifyVolume':
            return

        elif method is 'ListVolumesForAccount' and version == '1.0':
            test_name = 'OS-VOLID-a720b3c0-d1f0-11e1-9b23-0800200c9a66'
            LOG.info('Called Fake ListVolumesForAccount...')
            result = {'result': {
                'volumes': [{'volumeID': 5,
                             'name': test_name,
                             'accountID': 25,
                             'sliceCount': 1,
                             'totalSize': 1 * units.GiB,
                             'enable512e': True,
                             'access': "readWrite",
                             'status': "active",
                             'attributes': {},
                             'qos': None,
                             'iqn': test_name}]}}
            return result

        else:
            LOG.error('Crap, unimplemented API call in Fake:%s' % method)

    def fake_issue_api_request_fails(obj, method, params, version='1.0'):
        return {'error': {'code': 000,
                          'name': 'DummyError',
                          'message': 'This is a fake error response'},
                'id': 1}

    def fake_set_qos_by_volume_type(self, type_id, ctxt):
        return {'minIOPS': 500,
                'maxIOPS': 1000,
                'burstIOPS': 1000}

    def fake_volume_get(obj, key, default=None):
        return {'qos': 'fast'}

    def fake_update_cluster_status(self):
        return

    def fake_get_model_info(self, account, vid):
        return {'fake': 'fake-model'}

    def test_create_with_qos_type(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(SolidFireDriver, '_set_qos_by_volume_type',
                       self.fake_set_qos_by_volume_type)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': 'fast',
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertIsNotNone(model_update)

    def test_create_volume(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertIsNotNone(model_update)
        self.assertIsNone(model_update.get('provider_geometry', None))

    def test_create_volume_non_512(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        self.configuration.sf_emulate_512 = False
        sfv = SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertEqual(model_update.get('provider_geometry', None),
                         '4096 4096')
        self.configuration.sf_emulate_512 = True

    def test_create_snapshot(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(SolidFireDriver, '_get_model_info',
                       self.fake_get_model_info)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        testsnap = {'project_id': 'testprjid',
                    'name': 'testvol',
                    'volume_size': 1,
                    'id': 'b831c4d1-d1f0-11e1-9b23-0800200c9a66',
                    'volume_id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                    'volume_type_id': None,
                    'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        sfv.create_volume(testvol)
        sfv.create_snapshot(testsnap)

    def test_create_clone(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(SolidFireDriver, '_get_model_info',
                       self.fake_get_model_info)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        testvol_b = {'project_id': 'testprjid',
                     'name': 'testvol',
                     'size': 1,
                     'id': 'b831c4d1-d1f0-11e1-9b23-0800200c9a66',
                     'volume_type_id': None,
                     'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        sfv.create_cloned_volume(testvol_b, testvol)

    def test_initialize_connector_with_blocksizes(self):
        connector = {'initiator': 'iqn.2012-07.org.fake:01'}
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'volume_type_id': None,
                   'provider_location': '10.10.7.1:3260 iqn.2010-01.com.'
                                        'solidfire:87hg.uuid-2cc06226-cc'
                                        '74-4cb7-bd55-14aed659a0cc.4060 0',
                   'provider_auth': 'CHAP stack-1-a60e2611875f40199931f2'
                                    'c76370d66b 2FE0CQ8J196R',
                   'provider_geometry': '4096 4096',
                   'created_at': timeutils.utcnow(),
                   }

        sfv = SolidFireDriver(configuration=self.configuration)
        properties = sfv.initialize_connection(testvol, connector)
        self.assertEqual(properties['data']['physical_block_size'], '4096')
        self.assertEqual(properties['data']['logical_block_size'], '4096')

    def test_create_volume_with_qos(self):
        preset_qos = {}
        preset_qos['qos'] = 'fast'
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)

        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'metadata': [preset_qos],
                   'volume_type_id': None,
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        model_update = sfv.create_volume(testvol)
        self.assertIsNotNone(model_update)

    def test_create_volume_fails(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is inentional for this test
        self.stubs.Set(SolidFireDriver, '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'testvol',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        sfv = SolidFireDriver(configuration=self.configuration)
        try:
            sfv.create_volume(testvol)
            self.fail("Should have thrown Error")
        except Exception:
            pass

    def test_create_sfaccount(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        account = sfv._create_sfaccount('project-id')
        self.assertIsNotNone(account)

    def test_create_sfaccount_fails(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        account = sfv._create_sfaccount('project-id')
        self.assertIsNone(account)

    def test_get_sfaccount_by_name(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertIsNotNone(account)

    def test_get_sfaccount_by_name_fails(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        account = sfv._get_sfaccount_by_name('some-name')
        self.assertIsNone(account)

    def test_delete_volume(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        sfv.delete_volume(testvol)

    def test_delete_volume_fails_no_volume(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        try:
            sfv.delete_volume(testvol)
            self.fail("Should have thrown Error")
        except Exception:
            pass

    def test_delete_volume_fails_account_lookup(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is inentional for this test
        self.stubs.Set(SolidFireDriver, '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.SolidFireAccountNotFound,
                          sfv.delete_volume,
                          testvol)

    def test_get_cluster_info(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        sfv = SolidFireDriver(configuration=self.configuration)
        sfv._get_cluster_info()

    def test_get_cluster_info_fail(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is inentional for this test
        self.stubs.Set(SolidFireDriver, '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        sfv = SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.SolidFireAPIException,
                          sfv._get_cluster_info)

    def test_extend_volume(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        sfv.extend_volume(testvol, 2)

    def test_extend_volume_fails_no_volume(self):
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'not-found'}
        sfv = SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.VolumeNotFound,
                          sfv.extend_volume,
                          testvol, 2)

    def test_extend_volume_fails_account_lookup(self):
        # NOTE(JDG) This test just fakes update_cluster_status
        # this is intentional for this test
        self.stubs.Set(SolidFireDriver, '_update_cluster_status',
                       self.fake_update_cluster_status)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request_fails)
        testvol = {'project_id': 'testprjid',
                   'name': 'no-name',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        self.assertRaises(exception.SolidFireAccountNotFound,
                          sfv.extend_volume,
                          testvol, 2)

    def test_set_by_qos_spec_with_scoping(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        qos_ref = qos_specs.create(self.ctxt,
                                   'qos-specs-1', {'qos:minIOPS': '1000',
                                                   'qos:maxIOPS': '10000',
                                                   'qos:burstIOPS': '20000'})
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "100",
                                                 "qos:burstIOPS": "300",
                                                 "qos:maxIOPS": "200"})
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'])
        self.assertEqual(qos, self.expected_qos_results)

    def test_set_by_qos_spec(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        qos_ref = qos_specs.create(self.ctxt,
                                   'qos-specs-1', {'minIOPS': '1000',
                                                   'maxIOPS': '10000',
                                                   'burstIOPS': '20000'})
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "100",
                                                 "qos:burstIOPS": "300",
                                                 "qos:maxIOPS": "200"})
        qos_specs.associate_qos_with_type(self.ctxt,
                                          qos_ref['id'],
                                          type_ref['id'])
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'])
        self.assertEqual(qos, self.expected_qos_results)

    def test_set_by_qos_by_type_only(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "100",
                                                 "qos:burstIOPS": "300",
                                                 "qos:maxIOPS": "200"})
        qos = sfv._set_qos_by_volume_type(self.ctxt, type_ref['id'])
        self.assertEqual(qos, {'minIOPS': 100,
                               'maxIOPS': 200,
                               'burstIOPS': 300})

    def test_accept_transfer(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}
        expected = {'provider_auth': 'CHAP cinder-new_project 123456789012'}
        self.assertEqual(sfv.accept_transfer(self.ctxt,
                                             testvol,
                                             'new_user', 'new_project'),
                         expected)

    def test_retype(self):
        sfv = SolidFireDriver(configuration=self.configuration)
        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        type_ref = volume_types.create(self.ctxt,
                                       "type1", {"qos:minIOPS": "500",
                                                 "qos:burstIOPS": "2000",
                                                 "qos:maxIOPS": "1000"})
        diff = {'encryption': {}, 'qos_specs': {},
                'extra_specs': {'qos:burstIOPS': ('10000', u'2000'),
                                'qos:minIOPS': ('1000', u'500'),
                                'qos:maxIOPS': ('10000', u'1000')}}
        host = None
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        self.assertTrue(sfv.retype(self.ctxt,
                                   testvol,
                                   type_ref, diff, host))

    def test_retype_with_qos_spec(self):
        test_type = {'name': 'sf-1',
                     'qos_specs_id': 'fb0576d7-b4b5-4cad-85dc-ca92e6a497d1',
                     'deleted': False,
                     'created_at': '2014-02-06 04:58:11',
                     'updated_at': None,
                     'extra_specs': {},
                     'deleted_at': None,
                     'id': 'e730e97b-bc7d-4af3-934a-32e59b218e81'}

        test_qos_spec = {'id': 'asdfafdasdf',
                         'specs': {'minIOPS': '1000',
                                   'maxIOPS': '2000',
                                   'burstIOPS': '3000'}}

        def _fake_get_volume_type(ctxt, type_id):
            return test_type

        def _fake_get_qos_spec(ctxt, spec_id):
            return test_qos_spec

        self.stubs.Set(SolidFireDriver, '_issue_api_request',
                       self.fake_issue_api_request)
        self.stubs.Set(volume_types, 'get_volume_type',
                       _fake_get_volume_type)
        self.stubs.Set(qos_specs, 'get_qos_specs',
                       _fake_get_qos_spec)

        sfv = SolidFireDriver(configuration=self.configuration)

        diff = {'encryption': {}, 'extra_specs': {},
                'qos_specs': {'burstIOPS': ('10000', '2000'),
                              'minIOPS': ('1000', '500'),
                              'maxIOPS': ('10000', '1000')}}
        host = None
        testvol = {'project_id': 'testprjid',
                   'name': 'test_volume',
                   'size': 1,
                   'id': 'a720b3c0-d1f0-11e1-9b23-0800200c9a66',
                   'created_at': timeutils.utcnow()}

        sfv = SolidFireDriver(configuration=self.configuration)
        self.assertTrue(sfv.retype(self.ctxt,
                                   testvol,
                                   test_type, diff, host))
