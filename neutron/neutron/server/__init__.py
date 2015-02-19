#!/usr/bin/env python

# Copyright 2011 VMware, Inc.
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

# If ../neutron/__init__.py exists, add ../ to Python search path, so that
# it will override what happens to be installed in /usr/(local/)lib/python...

import eventlet
import sys

from oslo.config import cfg

from neutron.common import config
from neutron import service

from neutron.openstack.common import gettextutils
from neutron.openstack.common import log as logging
gettextutils.install('neutron', lazy=True)

LOG = logging.getLogger(__name__)


def main():
    eventlet.monkey_patch()

    # the configuration will be read into the cfg.CONF global data structure
    config.parse(sys.argv[1:])
    if not cfg.CONF.config_file:
        sys.exit(_("ERROR: Unable to find configuration file via the default"
                   " search paths (~/.neutron/, ~/, /etc/neutron/, /etc/) and"
                   " the '--config-file' option!"))
    try:
        pool = eventlet.GreenPool()

        neutron_api = service.serve_wsgi(service.NeutronApiService)
        api_thread = pool.spawn(neutron_api.wait)

        try:
            neutron_rpc = service.serve_rpc()
        except NotImplementedError:
            LOG.info(_("RPC was already started in parent process by plugin."))
        else:
            rpc_thread = pool.spawn(neutron_rpc.wait)

            # api and rpc should die together.  When one dies, kill the other.
            rpc_thread.link(lambda gt: api_thread.kill())
            api_thread.link(lambda gt: rpc_thread.kill())

        pool.waitall()
    except KeyboardInterrupt:
        pass
    except RuntimeError as e:
        sys.exit(_("ERROR: %s") % e)


if __name__ == "__main__":
    main()
