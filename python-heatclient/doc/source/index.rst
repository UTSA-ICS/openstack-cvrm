Python bindings to the OpenStack Heat API
=========================================

This is a client for OpenStack Heat API. There's a Python API
(the :mod:`heatclient` module), and a command-line script
(installed as :program:`heat`).

Python API
==========

In order to use the python api directly, you must first obtain an auth
token and identify which endpoint you wish to speak to::

  >>> tenant_id = 'b363706f891f48019483f8bd6503c54b'
  >>> heat_url = 'http://heat.example.org:8004/v1/%s' % tenant_id
  >>> auth_token = '3bcc3d3a03f44e3d8377f9247b0ad155'

Once you have done so, you can use the API like so::

  >>> from heatclient.client import Client
  >>> heat = Client('1', endpoint=heat_url, token=auth_token)

Reference
---------

.. toctree::
    :maxdepth: 1

    ref/index
    ref/v1/index

Command-line Tool
=================

In order to use the CLI, you must provide your OpenStack username,
password, tenant, and auth endpoint. Use the corresponding
configuration options (``--os-username``, ``--os-password``,
``--os-tenant-id``, and ``--os-auth-url``) or set them in environment
variables::

    export OS_USERNAME=user
    export OS_PASSWORD=pass
    export OS_TENANT_ID=b363706f891f48019483f8bd6503c54b
    export OS_AUTH_URL=http://auth.example.com:5000/v2.0

The command line tool will attempt to reauthenticate using your
provided credentials for every request. You can override this behavior
by manually supplying an auth token using ``--heat-url`` and
``--os-auth-token``. You can alternatively set these environment
variables::

    export HEAT_URL=http://heat.example.org:8004/v1/b363706f891f48019483f8bd6503c54b
    export OS_AUTH_TOKEN=3bcc3d3a03f44e3d8377f9247b0ad155

Once you've configured your authentication parameters, you can run
``heat help`` to see a complete listing of available commands.

Man Pages
=========

.. toctree::
    :maxdepth: 1

    man/heat

Contributing
============

Code is hosted `on GitHub`_. Submit bugs to the Heat project on
`Launchpad`_. Submit code to the openstack/python-heatclient project
using `Gerrit`_.

.. _on GitHub: https://github.com/openstack/python-heatclient
.. _Launchpad: https://launchpad.net/python-heatclient
.. _Gerrit: http://wiki.openstack.org/GerritWorkflow
