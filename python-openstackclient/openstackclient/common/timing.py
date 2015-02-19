#   Licensed under the Apache License, Version 2.0 (the "License"); you may
#   not use this file except in compliance with the License. You may obtain
#   a copy of the License at
#
#        http://www.apache.org/licenses/LICENSE-2.0
#
#   Unless required by applicable law or agreed to in writing, software
#   distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#   WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#   License for the specific language governing permissions and limitations
#   under the License.
#

"""Timing Implementation"""

import logging

from cliff import lister


class Timing(lister.Lister):
    """Show timing data"""

    log = logging.getLogger(__name__ + '.Timing')

    def take_action(self, parsed_args):
        self.log.debug('take_action(%s)' % parsed_args)

        column_headers = (
            'URL',
            'Seconds',
        )

        results = []
        total = 0.0
        for url, start, end in self.app.timing_data:
            seconds = end - start
            total += seconds
            results.append((url, seconds))
        results.append(('Total', total))
        return (
            column_headers,
            results,
        )
