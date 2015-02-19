# -*- coding: utf-8 -*-

#    Copyright (C) 2013 Rackspace Hosting Inc. All Rights Reserved.
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

import contextlib
import logging

from stevedore import driver

from taskflow import exceptions as exc
from taskflow.utils import misc


# NOTE(harlowja): this is the entrypoint namespace, not the module namespace.
BACKEND_NAMESPACE = 'taskflow.persistence'

LOG = logging.getLogger(__name__)


def fetch(conf, namespace=BACKEND_NAMESPACE, **kwargs):
    """Fetch a persistence backend with the given configuration.

    This fetch method will look for the entrypoint name in the entrypoint
    namespace, and then attempt to instantiate that entrypoint using the
    provided configuration and any persistence backend specific kwargs.

    NOTE(harlowja): to aid in making it easy to specify configuration and
    options to a backend the configuration (which is typical just a dictionary)
    can also be a uri string that identifies the entrypoint name and any
    configuration specific to that backend.

    For example, given the following configuration uri:

    mysql://<not-used>/?a=b&c=d

    This will look for the entrypoint named 'mysql' and will provide
    a configuration object composed of the uris parameters, in this case that
    is {'a': 'b', 'c': 'd'} to the constructor of that persistence backend
    instance.
    """
    backend_name = conf['connection']
    try:
        uri = misc.parse_uri(backend_name)
    except (TypeError, ValueError):
        pass
    else:
        backend_name = uri.scheme
        conf = misc.merge_uri(uri, conf.copy())
    LOG.debug('Looking for %r backend driver in %r', backend_name, namespace)
    try:
        mgr = driver.DriverManager(namespace, backend_name,
                                   invoke_on_load=True,
                                   invoke_args=(conf,),
                                   invoke_kwds=kwargs)
        return mgr.driver
    except RuntimeError as e:
        raise exc.NotFound("Could not find backend %s: %s" % (backend_name, e))


@contextlib.contextmanager
def backend(conf, namespace=BACKEND_NAMESPACE, **kwargs):
    """Fetches a backend, connects, upgrades, then closes it on completion.

    This allows a backend instance to be fetched, connected to, have its schema
    upgraded (if the schema is already up to date this is a no-op) and then
    used in a context manager statement with the backend being closed upon
    context manager exit.
    """
    with contextlib.closing(fetch(conf, namespace=namespace, **kwargs)) as be:
        with contextlib.closing(be.get_connection()) as conn:
            conn.upgrade()
        yield be
