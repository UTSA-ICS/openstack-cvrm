# Copyright (c) 2013 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.


from oslo.config import cfg

""" Arista ML2 Mechanism driver specific configuration knobs.

Following are user configurable options for Arista ML2 Mechanism
driver. The eapi_username, eapi_password, and eapi_host are
required options. Region Name must be the same that is used by
Keystone service. This option is available to support multiple
OpenStack/Neutron controllers.
"""

ARISTA_DRIVER_OPTS = [
    cfg.StrOpt('eapi_username',
               default='',
               help=_('Username for Arista EOS. This is required field.'
                      'if not set, all communications to Arista EOS'
                      'will fail')),
    cfg.StrOpt('eapi_password',
               default='',
               secret=True,  # do not expose value in the logs
               help=_('Password for Arista EOS. This is required field.'
                      'if not set, all communications to Arista EOS'
                      'will fail')),
    cfg.StrOpt('eapi_host',
               default='',
               help=_('Arista EOS IP address. This is required field.'
                      'If not set, all communications to Arista EOS'
                      'will fail')),
    cfg.BoolOpt('use_fqdn',
                default=True,
                help=_('Defines if hostnames are sent to Arista EOS as FQDNs'
                       '("node1.domain.com") or as short names ("node1").'
                       'This is optional. If not set, a value of "True"'
                       'is assumed.')),
    cfg.IntOpt('sync_interval',
               default=180,
               help=_('Sync interval in seconds between Neutron plugin and'
                      'EOS. This interval defines how often the'
                      'synchronization is performed. This is an optional'
                      'field. If not set, a value of 180 seconds is assumed')),
    cfg.StrOpt('region_name',
               default='RegionOne',
               help=_('Defines Region Name that is assigned to this OpenStack'
                      'Controller. This is useful when multiple'
                      'OpenStack/Neutron controllers are managing the same'
                      'Arista HW clusters. Note that this name must match with'
                      'the region name registered (or known) to keystone'
                      'service. Authentication with Keysotne is performed by'
                      'EOS. This is optional. If not set, a value of'
                      '"RegionOne" is assumed'))
]

cfg.CONF.register_opts(ARISTA_DRIVER_OPTS, "ml2_arista")
