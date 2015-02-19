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

import datetime
import uuid

from keystone.common import dependency
from keystone.contrib.revoke import model
from keystone.openstack.common import timeutils
from keystone.tests import test_v3
from keystone import token


def _future_time_string():
    expire_delta = datetime.timedelta(seconds=1000)
    future_time = timeutils.utcnow() + expire_delta
    return timeutils.isotime(future_time)


@dependency.requires('revoke_api')
class OSRevokeTests(test_v3.RestfulTestCase):
    EXTENSION_NAME = 'revoke'
    EXTENSION_TO_ADD = 'revoke_extension'

    def test_get_empty_list(self):
        resp = self.get('/OS-REVOKE/events')
        self.assertEqual([], resp.json_body['events'])

    def _blank_event(self):
        return {}

    # The two values will be the same with the exception of
    # 'issued_before' which is set when the event is recorded.
    def assertReportedEventMatchesRecorded(self, event, sample, before_time):
        after_time = timeutils.utcnow()
        event_issued_before = timeutils.normalize_time(
            timeutils.parse_isotime(event['issued_before']))
        self.assertTrue(
            before_time <= event_issued_before,
            'invalid event issued_before time; %s is not later than %s.' % (
                timeutils.isotime(event_issued_before, subsecond=True),
                timeutils.isotime(before_time, subsecond=True)))
        self.assertTrue(
            event_issued_before <= after_time,
            'invalid event issued_before time; %s is not earlier than %s.' % (
                timeutils.isotime(event_issued_before, subsecond=True),
                timeutils.isotime(after_time, subsecond=True)))
        del (event['issued_before'])
        self.assertEqual(sample, event)

    def test_revoked_token_in_list(self):
        user_id = uuid.uuid4().hex
        expires_at = token.default_expire_time()
        sample = self._blank_event()
        sample['user_id'] = unicode(user_id)
        sample['expires_at'] = unicode(timeutils.isotime(expires_at))
        before_time = timeutils.utcnow()
        self.revoke_api.revoke_by_expiration(user_id, expires_at)
        resp = self.get('/OS-REVOKE/events')
        events = resp.json_body['events']
        self.assertEqual(len(events), 1)
        self.assertReportedEventMatchesRecorded(events[0], sample, before_time)

    def test_disabled_project_in_list(self):
        project_id = uuid.uuid4().hex
        sample = dict()
        sample['project_id'] = unicode(project_id)
        before_time = timeutils.utcnow()
        self.revoke_api.revoke(
            model.RevokeEvent(project_id=project_id))

        resp = self.get('/OS-REVOKE/events')
        events = resp.json_body['events']
        self.assertEqual(len(events), 1)
        self.assertReportedEventMatchesRecorded(events[0], sample, before_time)

    def test_disabled_domain_in_list(self):
        domain_id = uuid.uuid4().hex
        sample = dict()
        sample['domain_id'] = unicode(domain_id)
        before_time = timeutils.utcnow()
        self.revoke_api.revoke(
            model.RevokeEvent(domain_id=domain_id))

        resp = self.get('/OS-REVOKE/events')
        events = resp.json_body['events']
        self.assertEqual(len(events), 1)
        self.assertReportedEventMatchesRecorded(events[0], sample, before_time)

    def test_list_since_invalid(self):
        self.get('/OS-REVOKE/events?since=blah', expected_status=400)

    def test_list_since_valid(self):
        resp = self.get('/OS-REVOKE/events?since=2013-02-27T18:30:59.999999Z')
        events = resp.json_body['events']
        self.assertEqual(len(events), 0)

    def test_since_future_time_no_events(self):
        domain_id = uuid.uuid4().hex
        sample = dict()
        sample['domain_id'] = unicode(domain_id)

        self.revoke_api.revoke(
            model.RevokeEvent(domain_id=domain_id))

        resp = self.get('/OS-REVOKE/events')
        events = resp.json_body['events']
        self.assertEqual(len(events), 1)

        resp = self.get('/OS-REVOKE/events?since=%s' % _future_time_string())
        events = resp.json_body['events']
        self.assertEqual([], events)
