===============
keystone-manage
===============

---------------------------
Keystone Management Utility
---------------------------

:Author: openstack@lists.openstack.org
:Date:   2014-02-14
:Copyright: OpenStack Foundation
:Version: 2014.1
:Manual section: 1
:Manual group: cloud computing

SYNOPSIS
========

  keystone-manage [options]

DESCRIPTION
===========

``keystone-manage`` is the command line tool which interacts with the Keystone
service to initialize and update data within Keystone. Generally,
``keystone-manage`` is only used for operations that cannot be accomplished
with the HTTP API, such data import/export and database migrations.

USAGE
=====

    ``keystone-manage [options] action [additional args]``

General keystone-manage options:
--------------------------------

* ``--help`` : display verbose help output.

Invoking ``keystone-manage`` by itself will give you some usage information.

Available commands:

* ``db_sync``: Sync the database.
* ``db_version``: Print the current migration version of the database.
* ``pki_setup``: Initialize the certificates used to sign tokens.
* ``ssl_setup``: Generate certificates for SSL.
* ``token_flush``: Purge expired tokens.

OPTIONS
=======

  -h, --help            show this help message and exit
  --config-dir DIR      Path to a config directory to pull \*.conf files from.
                        This file set is sorted, so as to provide a
                        predictable parse order if individual options are
                        over-ridden. The set is parsed after the file(s)
                        specified via previous --config-file, arguments hence
                        over-ridden options in the directory take precedence.
  --config-file PATH    Path to a config file to use. Multiple config files
                        can be specified, with values in later files taking
                        precedence. The default files used are: None
  --debug, -d           Print debugging output (set logging level to DEBUG
                        instead of default WARNING level).
  --log-config-append PATH, --log_config PATH
                        The name of logging configuration file. It does not
                        disable existing loggers, but just appends specified
                        logging configuration to any other existing logging
                        options. Please see the Python logging module
                        documentation for details on logging configuration
                        files.
  --log-date-format DATE_FORMAT
                        Format string for %(asctime)s in log records. Default:
                        None
  --log-dir LOG_DIR, --logdir LOG_DIR
                        (Optional) The base directory used for relative --log-
                        file paths
  --log-file PATH, --logfile PATH
                        (Optional) Name of log file to output to. If no
                        default is set, logging will go to stdout.
  --log-format FORMAT   DEPRECATED. A logging.Formatter log message format
                        string which may use any of the available
                        logging.LogRecord attributes. This option is
                        deprecated. Please use logging_context_format_string
                        and logging_default_format_string instead.
  --nodebug             The inverse of --debug
  --nostandard-threads  The inverse of --standard-threads
  --nouse-syslog        The inverse of --use-syslog
  --nouse-syslog-rfc-format
                        The inverse of --use-syslog-rfc-format
  --noverbose           The inverse of --verbose
  --pydev-debug-host PYDEV_DEBUG_HOST
                        Host to connect to for remote debugger.
  --pydev-debug-port PYDEV_DEBUG_PORT
                        Port to connect to for remote debugger.
  --standard-threads    Do not monkey-patch threading system modules.
  --syslog-log-facility SYSLOG_LOG_FACILITY
                        Syslog facility to receive log lines
  --use-syslog          Use syslog for logging. Existing syslog format is
                        DEPRECATED during I, and then will be changed in J to
                        honor RFC5424
  --use-syslog-rfc-format
                        (Optional) Use syslog rfc5424 format for logging. If
                        enabled, will add APP-NAME (RFC5424) before the MSG
                        part of the syslog message. The old format without
                        APP-NAME is deprecated in I, and will be removed in J.
  --verbose, -v         Print more verbose output (set logging level to INFO
                        instead of default WARNING level).
  --version             show program's version number and exit

FILES
=====

None

SEE ALSO
========

* `OpenStack Keystone <http://keystone.openstack.org>`__

SOURCE
======

* Keystone is sourced in GitHub `Keystone <http://github.com/openstack/keystone>`__
* Keystone bugs are managed at Launchpad `Keystone <https://bugs.launchpad.net/keystone>`__
