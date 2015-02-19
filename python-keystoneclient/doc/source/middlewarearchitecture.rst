..
      Copyright 2011-2013 OpenStack Foundation
      All Rights Reserved.

      Licensed under the Apache License, Version 2.0 (the "License"); you may
      not use this file except in compliance with the License. You may obtain
      a copy of the License at

          http://www.apache.org/licenses/LICENSE-2.0

      Unless required by applicable law or agreed to in writing, software
      distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
      WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
      License for the specific language governing permissions and limitations
      under the License.

=======================
Middleware Architecture
=======================

Abstract
========

The Keystone middleware architecture supports a common authentication protocol
in use between the OpenStack projects. By using keystone as a common
authentication and authorization mechanism, the OpenStack project can plug in
to existing authentication and authorization systems in use by existing
environments.

In this document, we describe the architecture and responsibilities of the
authentication middleware which acts as the internal API mechanism for
OpenStack projects based on the WSGI standard.

This documentation describes the implementation in
:class:`keystoneclient.middleware.auth_token`

Specification Overview
======================

'Authentication' is the process of determining that users are who they say they
are. Typically, 'authentication protocols' such as HTTP Basic Auth, Digest
Access, public key, token, etc, are used to verify a user's identity. In this
document, we define an ''authentication component'' as a software module that
implements an authentication protocol for an OpenStack service. OpenStack is
using a token based mechanism to represent authentication and authorization.

At a high level, an authentication middleware component is a proxy that
intercepts HTTP calls from clients and populates HTTP headers in the request
context for other WSGI middleware or applications to use. The general flow
of the middleware processing is:

* clear any existing authorization headers to prevent forgery
* collect the token from the existing HTTP request headers
* validate the token

  * if valid, populate additional headers representing the identity that has
    been authenticated and authorized
  * if invalid, or no token present, reject the request (HTTPUnauthorized)
    or pass along a header indicating the request is unauthorized (configurable
    in the middleware)
  * if the keystone service is unavailable to validate the token, reject
    the request with HTTPServiceUnavailable.

.. _authComponent:

Authentication Component
------------------------

Figure 1. Authentication Component

.. image:: images/graphs_authComp.svg
   :width: 100%
   :height: 180
   :alt: An Authentication Component

The middleware may also be configured to operate in a 'delegated mode'.
In this mode, the decision to reject an unauthenticated client is delegated to
the OpenStack service, as illustrated in :ref:`authComponentDelegated`.

Here, requests are forwarded to the OpenStack service with an identity status
message that indicates whether the client's identity has been confirmed or is
indeterminate. It is the OpenStack service that decides whether or not a reject
message should be sent to the client.

.. _authComponentDelegated:

Authentication Component (Delegated Mode)
-----------------------------------------

Figure 2. Authentication Component (Delegated Mode)

.. image:: images/graphs_authCompDelegate.svg
   :width: 100%
   :height: 180
   :alt: An Authentication Component (Delegated Mode)

.. _deployStrategies:

Deployment Strategy
===================

The middleware is intended to be used inline with OpenStack wsgi components,
based on the Oslo WSGI middleware class. It is typically deployed
as a configuration element in a paste configuration pipeline of other
middleware components, with the pipeline terminating in the service
application. The middleware conforms to the python WSGI standard [PEP-333]_.
In initializing the middleware, a configuration item (which acts like a python
dictionary) is passed to the middleware with relevant configuration options.

Configuration
-------------

The middleware is configured within the config file of the main application as
a WSGI component. Example for the auth_token middleware::

    [app:myService]
    paste.app_factory = myService:app_factory

    [pipeline:main]
    pipeline = authtoken myService

    [filter:authtoken]
    paste.filter_factory = keystoneclient.middleware.auth_token:filter_factory

    # Prefix to prepend at the beginning of the path (string
    # value)
    #auth_admin_prefix=

    # Host providing the admin Identity API endpoint (string
    # value)
    auth_host=127.0.0.1

    # Port of the admin Identity API endpoint (integer value)
    auth_port=35357

    # Protocol of the admin Identity API endpoint(http or https)
    # (string value)
    auth_protocol=https

    # Complete public Identity API endpoint (string value)
    #auth_uri=<None>

    # API version of the admin Identity API endpoint (string
    # value)
    #auth_version=<None>

    # Do not handle authorization requests within the middleware,
    # but delegate the authorization decision to downstream WSGI
    # components (boolean value)
    #delay_auth_decision=false

    # Request timeout value for communicating with Identity API
    # server. (boolean value)
    #http_connect_timeout=<None>

    # How many times are we trying to reconnect when communicating
    # with Identity API Server. (integer value)
    #http_request_max_retries=3

    # Single shared secret with the Keystone configuration used
    # for bootstrapping a Keystone installation, or otherwise
    # bypassing the normal authentication process. (string value)
    #admin_token=<None>

    # Keystone account username (string value)
    #admin_user=<None>

    # Keystone account password (string value)
    admin_password=SuperSekretPassword

    # Keystone service account tenant name to validate user tokens
    # (string value)
    #admin_tenant_name=admin

    # Env key for the swift cache (string value)
    #cache=<None>

    # Required if Keystone server requires client certificate
    # (string value)
    #certfile=<None>

    # Required if Keystone server requires client certificate
    # (string value)
    #keyfile=<None>

    # A PEM encoded Certificate Authority to use when verifying
    # HTTPs connections. Defaults to system CAs. (string value)
    #cafile=<None>

    # Verify HTTPS connections. (boolean value)
    #insecure=false

    # Directory used to cache files related to PKI tokens (string
    # value)
    #signing_dir=<None>

    # If defined, the memcache server(s) to use for caching (list
    # value)
    # Deprecated group/name - [DEFAULT]/memcache_servers
    #memcached_servers=<None>

    # In order to prevent excessive requests and validations, the
    # middleware uses an in-memory cache for the tokens the
    # Keystone API returns. This is only valid if memcache_servers
    # is defined. Set to -1 to disable caching completely.
    # (integer value)
    #token_cache_time=300

    # Value only used for unit testing (integer value)
    #revocation_cache_time=1

    # (optional) if defined, indicate whether token data should be
    # authenticated or authenticated and encrypted. Acceptable
    # values are MAC or ENCRYPT.  If MAC, token data is
    # authenticated (with HMAC) in the cache. If ENCRYPT, token
    # data is encrypted and authenticated in the cache. If the
    # value is not one of these options or empty, auth_token will
    # raise an exception on initialization. (string value)
    #memcache_security_strategy=<None>

    # (optional, mandatory if memcache_security_strategy is
    # defined) this string is used for key derivation. (string
    # value)
    #memcache_secret_key=<None>

    # (optional) indicate whether to set the X-Service-Catalog
    # header. If False, middleware will not ask for service
    # catalog on token validation and will not set the X-Service-
    # Catalog header. (boolean value)
    #include_service_catalog=true

    # Used to control the use and type of token binding. Can be
    # set to: "disabled" to not check token binding. "permissive"
    # (default) to validate binding information if the bind type
    # is of a form known to the server and ignore it if not.
    # "strict" like "permissive" but if the bind type is unknown
    # the token will be rejected. "required" any form of token
    # binding is needed to be allowed. Finally the name of a
    # binding method that must be present in tokens. (string
    # value)
    #enforce_token_bind=permissive

For services which have a separate paste-deploy ini file, auth_token middleware
can be alternatively configured in [keystone_authtoken] section in the main
config file. For example in Nova, all middleware parameters can be removed
from api-paste.ini::

    [filter:authtoken]
    paste.filter_factory = keystoneclient.middleware.auth_token:filter_factory

and set in nova.conf::

    [DEFAULT]
    ...
    auth_strategy=keystone

    [keystone_authtoken]
    auth_host = 127.0.0.1
    auth_port = 35357
    auth_protocol = http
    admin_user = admin
    admin_password = SuperSekretPassword
    admin_tenant_name = service
    # Any of the options that could be set in api-paste.ini can be set here.

Note that middleware parameters in paste config take priority, they must be
removed to use values in [keystone_authtoken] section.

Configuration Options
---------------------

* ``auth_admin_prefix``: Prefix to prepend at the beginning of the path
* ``auth_host``: (required) the host providing the keystone service API endpoint
  for validating and requesting tokens
* ``auth_port``: (optional, default `35357`) the port used to validate tokens
* ``auth_protocol``: (optional, default `https`)
* ``auth_uri``: (optional, defaults to
  `auth_protocol`://`auth_host`:`auth_port`)
* ``auth_version``: API version of the admin Identity API endpoint
* ``delay_auth_decision``: (optional, default `0`) (off). If on, the middleware
  will not reject invalid auth requests, but will delegate that decision to
  downstream WSGI components.
* ``http_connect_timeout``: (optional) Request timeout value for communicating
  with Identity API server.
* ``http_request_max_retries``: (default 3) How many times are we trying to
  reconnect when communicating with Identity API Server.
* ``http_handler``: (optional) Allows to pass in the name of a fake
  http_handler callback function used instead of `httplib.HTTPConnection` or
  `httplib.HTTPSConnection`. Useful for unit testing where network is not
  available.

* ``admin_token``: either this or the following three options are required. If
  set, this is a single shared secret with the keystone configuration used to
  validate tokens.
* ``admin_user``, ``admin_password``, ``admin_tenant_name``: if ``admin_token``
  is not set, or invalid, then admin_user, admin_password, and
  admin_tenant_name are defined as a service account which is expected to have
  been previously configured in Keystone to validate user tokens.

* ``cache``: (optional) Env key for the swift cache

* ``certfile``: (required, if Keystone server requires client cert)
* ``keyfile``: (required, if Keystone server requires client cert)  This can be
  the same as the certfile if the certfile includes the private key.
* ``cafile``: (optional, defaults to use system CA bundle) the path to a PEM
  encoded CA file/bundle that will be used to verify HTTPS connections.
* ``insecure``: (optional, default `False`) Don't verify HTTPS connections
  (overrides `cafile`).

* ``signing_dir``: (optional) Directory used to cache files related to PKI
  tokens

* ``memcached_servers``: (optional) If defined, the memcache server(s) to use
  for caching
* ``token_cache_time``: (default 300) In order to prevent excessive requests
  and validations, the middleware uses an in-memory cache for the tokens the
  Keystone API returns. This is only valid if memcache_servers s defined. Set
  to -1 to disable caching completely.
* ``memcache_security_strategy``: (optional) if defined, indicate whether token
  data should be authenticated or authenticated and encrypted. Acceptable
  values are MAC or ENCRYPT.  If MAC, token data is authenticated (with HMAC)
  in the cache. If ENCRYPT, token data is encrypted and authenticated in the
  cache. If the value is not one of these options or empty, auth_token will
  raise an exception on initialization.
* ``memcache_secret_key``: (mandatory if memcache_security_strategy is defined)
   this string is used for key derivation.
* ``include_service_catalog``: (optional, default `True`) Indicate whether to
  set the X-Service-Catalog header. If False, middleware will not ask for
  service catalog on token validation and will not set the X-Service-Catalog
  header.
* ``enforce_token_bind``: (default ``permissive``) Used to control the use and
  type of token binding. Can be set to: "disabled" to not check token binding.
  "permissive" (default) to validate binding information if the bind type is of
  a form known to the server and ignore it if not. "strict" like "permissive"
  but if the bind type is unknown the token will be rejected. "required" any
  form of token binding is needed to be allowed. Finally the name of a binding
  method that must be present in tokens.

Caching for improved response
-----------------------------

In order to prevent excessive requests and validations, the middleware uses an
in-memory cache for the tokens the keystone API returns. Keep in mind that
invalidated tokens may continue to work if they are still in the token cache,
so token_cache_time is configurable. For larger deployments, the middleware
also supports memcache based caching.

* ``memcached_servers``: (optonal) if defined, the memcache server(s) to use for
  cacheing. It will be ignored if Swift MemcacheRing is used instead.
* ``token_cache_time``: (optional, default 300 seconds) Set to -1 to disable
  caching completely.

When deploying auth_token middleware with Swift, user may elect
to use Swift MemcacheRing instead of the local Keystone memcache.
The Swift MemcacheRing object is passed in from the request environment
and it defaults to 'swift.cache'. However it could be
different, depending on deployment. To use Swift MemcacheRing, you must
provide the ``cache`` option.

* ``cache``: (optional) if defined, the environment key where the Swift
  MemcacheRing object is stored.

Memcached and System Time
=========================

When using `memcached`_ with ``auth_token`` middleware, ensure that the system
time of memcached hosts is set to UTC. Memcached uses the host's system
time in determining whether a key has expired, whereas Keystone sets
key expiry in UTC.  The timezone used by Keystone and memcached must
match if key expiry is to behave as expected.

.. _`memcached`: http://memcached.org/

Memcache Protection
===================

When using memcached, we are storing user tokens and token validation
information into the cache as raw data. Which means that anyone who
has access to the memcache servers can read and modify data stored
there. To mitigate this risk, ``auth_token`` middleware provides an
option to authenticate and optionally encrypt the token data stored in
the cache.

* ``memcache_security_strategy``: (optional) if defined, indicate
  whether token data should be authenticated or authenticated and
  encrypted. Acceptable values are ``MAC`` or ``ENCRYPT``. If ``MAC``,
  token data is authenticated (with HMAC) in the cache. If
  ``ENCRYPT``, token data is encrypted and authenticated in the
  cache. If the value is not one of these options or empty,
  ``auth_token`` will raise an exception on initialization.
* ``memcache_secret_key``: (optional, mandatory if
  ``memcache_security_strategy`` is defined) this string is used for
  key derivation. If ``memcache_security_strategy`` is defined and
  ``memcache_secret_key`` is absent, ``auth_token`` will raise an
  exception on initialization.

Exchanging User Information
===========================

The middleware expects to find a token representing the user with the header
``X-Auth-Token`` or ``X-Storage-Token``. `X-Storage-Token` is supported for
swift/cloud files and for legacy Rackspace use. If the token isn't present and
the middleware is configured to not delegate auth responsibility, it will
respond to the HTTP request with HTTPUnauthorized, returning the header
``WWW-Authenticate`` with the value `Keystone uri='...'` to indicate where to
request a token. The auth_uri returned is configured  with the middleware.

The authentication middleware extends the HTTP request with the header
``X-Identity-Status``.  If a request is successfully authenticated, the value
is set to `Confirmed`. If the middleware is delegating the auth decision to the
service, then the status is set to `Invalid` if the auth request was
unsuccessful.

Extended the request with additional User Information
-----------------------------------------------------

:py:class:`keystoneclient.middleware.auth_token.AuthProtocol` extends the
request with additional information if the user has been authenticated. See the
"What we add to the request for use by the OpenStack service" section in
:py:mod:`keystoneclient.middleware.auth_token` for the list of fields set by
the auth_token middleware.


References
==========

.. [PEP-333] pep0333 Phillip J Eby.  'Python Web Server Gateway Interface
    v1.0.''  http://www.python.org/dev/peps/pep-0333/.
