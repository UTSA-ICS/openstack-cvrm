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

"""
Command-line interface to the Heat API.
"""

from __future__ import print_function

import argparse
import logging
import sys

import six
import six.moves.urllib.parse as urlparse

from keystoneclient.auth.identity import v2 as v2_auth
from keystoneclient.auth.identity import v3 as v3_auth
from keystoneclient import discover
from keystoneclient.openstack.common.apiclient import exceptions as ks_exc
from keystoneclient import session as kssession

import heatclient
from heatclient import client as heat_client
from heatclient.common import utils
from heatclient import exc
from heatclient.openstack.common.gettextutils import _
from heatclient.openstack.common import importutils
from heatclient.openstack.common import strutils

logger = logging.getLogger(__name__)
osprofiler_profiler = importutils.try_import("osprofiler.profiler")


class HeatShell(object):

    def _append_global_identity_args(self, parser):
        # FIXME(gyee): these are global identity (Keystone) arguments which
        # should be consistent and shared by all service clients. Therefore,
        # they should be provided by python-keystoneclient. We will need to
        # refactor this code once this functionality is avaible in
        # python-keystoneclient.
        parser.add_argument('-k', '--insecure',
                            default=False,
                            action='store_true',
                            help='Explicitly allow heatclient to perform '
                            '\"insecure SSL\" (https) requests. The server\'s '
                            'certificate will not be verified against any '
                            'certificate authorities. This option should '
                            'be used with caution.')

        parser.add_argument('--os-cert',
                            help='Path of certificate file to use in SSL '
                            'connection. This file can optionally be '
                            'prepended with the private key.')

        # for backward compatibility only
        parser.add_argument('--cert-file',
                            dest='os_cert',
                            help='DEPRECATED! Use --os-cert.')

        parser.add_argument('--os-key',
                            help='Path of client key to use in SSL '
                            'connection. This option is not necessary '
                            'if your key is prepended to your cert file.')

        parser.add_argument('--key-file',
                            dest='os_key',
                            help='DEPRECATED! Use --os-key.')

        parser.add_argument('--os-cacert',
                            metavar='<ca-certificate-file>',
                            dest='os_cacert',
                            default=utils.env('OS_CACERT'),
                            help='Path of CA TLS certificate(s) used to '
                            'verify the remote server\'s certificate. '
                            'Without this option glance looks for the '
                            'default system CA certificates.')

        parser.add_argument('--ca-file',
                            dest='os_cacert',
                            help='DEPRECATED! Use --os-cacert.')

        parser.add_argument('--os-username',
                            default=utils.env('OS_USERNAME'),
                            help='Defaults to env[OS_USERNAME].')

        parser.add_argument('--os_username',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-user-id',
                            default=utils.env('OS_USER_ID'),
                            help='Defaults to env[OS_USER_ID].')

        parser.add_argument('--os_user_id',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-user-domain-id',
                            default=utils.env('OS_USER_DOMAIN_ID'),
                            help='Defaults to env[OS_USER_DOMAIN_ID].')

        parser.add_argument('--os_user_domain_id',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-user-domain-name',
                            default=utils.env('OS_USER_DOMAIN_NAME'),
                            help='Defaults to env[OS_USER_DOMAIN_NAME].')

        parser.add_argument('--os_user_domain_name',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-project-id',
                            default=utils.env('OS_PROJECT_ID'),
                            help='Another way to specify tenant ID. '
                                 'This option is mutually exclusive with '
                                 ' --os-tenant-id. '
                                 'Defaults to env[OS_PROJECT_ID].')

        parser.add_argument('--os_project_id',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-project-name',
                            default=utils.env('OS_PROJECT_NAME'),
                            help='Another way to specify tenant name. '
                                 'This option is mutually exclusive with '
                                 ' --os-tenant-name. '
                                 'Defaults to env[OS_PROJECT_NAME].')

        parser.add_argument('--os_project_name',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-project-domain-id',
                            default=utils.env('OS_PROJECT_DOMAIN_ID'),
                            help='Defaults to env[OS_PROJECT_DOMAIN_ID].')

        parser.add_argument('--os_project_domain_id',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-project-domain-name',
                            default=utils.env('OS_PROJECT_DOMAIN_NAME'),
                            help='Defaults to env[OS_PROJECT_DOMAIN_NAME].')

        parser.add_argument('--os_project_domain_name',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-password',
                            default=utils.env('OS_PASSWORD'),
                            help='Defaults to env[OS_PASSWORD].')

        parser.add_argument('--os_password',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-tenant-id',
                            default=utils.env('OS_TENANT_ID'),
                            help='Defaults to env[OS_TENANT_ID].')

        parser.add_argument('--os_tenant_id',
                            default=utils.env('OS_TENANT_ID'),
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-tenant-name',
                            default=utils.env('OS_TENANT_NAME'),
                            help='Defaults to env[OS_TENANT_NAME].')

        parser.add_argument('--os_tenant_name',
                            default=utils.env('OS_TENANT_NAME'),
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-auth-url',
                            default=utils.env('OS_AUTH_URL'),
                            help='Defaults to env[OS_AUTH_URL].')

        parser.add_argument('--os_auth_url',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-region-name',
                            default=utils.env('OS_REGION_NAME'),
                            help='Defaults to env[OS_REGION_NAME].')

        parser.add_argument('--os_region_name',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-auth-token',
                            default=utils.env('OS_AUTH_TOKEN'),
                            help='Defaults to env[OS_AUTH_TOKEN].')

        parser.add_argument('--os_auth_token',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-service-type',
                            default=utils.env('OS_SERVICE_TYPE'),
                            help='Defaults to env[OS_SERVICE_TYPE].')

        parser.add_argument('--os_service_type',
                            help=argparse.SUPPRESS)

        parser.add_argument('--os-endpoint-type',
                            default=utils.env('OS_ENDPOINT_TYPE'),
                            help='Defaults to env[OS_ENDPOINT_TYPE].')

        parser.add_argument('--os_endpoint_type',
                            help=argparse.SUPPRESS)

    def get_base_parser(self):
        parser = argparse.ArgumentParser(
            prog='heat',
            description=__doc__.strip(),
            epilog='See "heat help COMMAND" '
                   'for help on a specific command.',
            add_help=False,
            formatter_class=HelpFormatter,
        )

        # Global arguments
        parser.add_argument('-h', '--help',
                            action='store_true',
                            help=argparse.SUPPRESS)

        parser.add_argument('--version',
                            action='version',
                            version=heatclient.__version__,
                            help="Shows the client version and exits.")

        parser.add_argument('-d', '--debug',
                            default=bool(utils.env('HEATCLIENT_DEBUG')),
                            action='store_true',
                            help='Defaults to env[HEATCLIENT_DEBUG].')

        parser.add_argument('-v', '--verbose',
                            default=False, action="store_true",
                            help="Print more verbose output.")

        parser.add_argument('--api-timeout',
                            help='Number of seconds to wait for an '
                                 'API response, '
                                 'defaults to system socket timeout')

        # os-no-client-auth tells heatclient to use token, instead of
        # env[OS_AUTH_URL]
        parser.add_argument('--os-no-client-auth',
                            default=utils.env('OS_NO_CLIENT_AUTH'),
                            action='store_true',
                            help="Do not contact keystone for a token. "
                                 "Defaults to env[OS_NO_CLIENT_AUTH].")

        parser.add_argument('--heat-url',
                            default=utils.env('HEAT_URL'),
                            help='Defaults to env[HEAT_URL].')

        parser.add_argument('--heat_url',
                            help=argparse.SUPPRESS)

        parser.add_argument('--heat-api-version',
                            default=utils.env('HEAT_API_VERSION', default='1'),
                            help='Defaults to env[HEAT_API_VERSION] or 1.')

        parser.add_argument('--heat_api_version',
                            help=argparse.SUPPRESS)

        # This unused option should remain so that scripts that
        # use it do not break. It is suppressed so it will not
        # appear in the help.
        parser.add_argument('-t', '--token-only',
                            default=bool(False),
                            action='store_true',
                            help=argparse.SUPPRESS)

        parser.add_argument('--include-password',
                            default=bool(utils.env('HEAT_INCLUDE_PASSWORD')),
                            action='store_true',
                            help='Send os-username and os-password to heat.')

        # FIXME(gyee): this method should come from python-keystoneclient.
        # Will refactor this code once it is available.
        # https://bugs.launchpad.net/python-keystoneclient/+bug/1332337

        self._append_global_identity_args(parser)

        if osprofiler_profiler:
            parser.add_argument('--profile',
                                metavar='HMAC_KEY',
                                help='HMAC key to use for encrypting context '
                                'data for performance profiling of operation. '
                                'This key should be the value of HMAC key '
                                'configured in osprofiler middleware in heat, '
                                'it is specified in the paste configuration '
                                '(/etc/heat/api-paste.ini). '
                                'Without the key, profiling will not be '
                                'triggered even if osprofiler is enabled '
                                'on server side.')
        return parser

    def get_subcommand_parser(self, version):
        parser = self.get_base_parser()

        self.subcommands = {}
        subparsers = parser.add_subparsers(metavar='<subcommand>')
        submodule = utils.import_versioned_module(version, 'shell')
        self._find_actions(subparsers, submodule)
        self._find_actions(subparsers, self)
        self._add_bash_completion_subparser(subparsers)

        return parser

    def _add_bash_completion_subparser(self, subparsers):
        subparser = subparsers.add_parser(
            'bash_completion',
            add_help=False,
            formatter_class=HelpFormatter
        )
        self.subcommands['bash_completion'] = subparser
        subparser.set_defaults(func=self.do_bash_completion)

    def _find_actions(self, subparsers, actions_module):
        for attr in (a for a in dir(actions_module) if a.startswith('do_')):
            # I prefer to be hyphen-separated instead of underscores.
            command = attr[3:].replace('_', '-')
            callback = getattr(actions_module, attr)
            desc = callback.__doc__ or ''
            help = desc.strip().split('\n')[0]
            arguments = getattr(callback, 'arguments', [])

            subparser = subparsers.add_parser(command,
                                              help=help,
                                              description=desc,
                                              add_help=False,
                                              formatter_class=HelpFormatter)
            subparser.add_argument('-h', '--help',
                                   action='help',
                                   help=argparse.SUPPRESS)
            self.subcommands[command] = subparser
            for (args, kwargs) in arguments:
                subparser.add_argument(*args, **kwargs)
            subparser.set_defaults(func=callback)

    def _setup_logging(self, debug):
        log_lvl = logging.DEBUG if debug else logging.WARNING
        logging.basicConfig(
            format="%(levelname)s (%(module)s) %(message)s",
            level=log_lvl)
        logging.getLogger('iso8601').setLevel(logging.WARNING)
        logging.getLogger('urllib3.connectionpool').setLevel(logging.WARNING)

    def _setup_verbose(self, verbose):
        if verbose:
            exc.verbose = 1

    def _discover_auth_versions(self, session, auth_url):
        # discover the API versions the server is supporting base on the
        # given URL
        v2_auth_url = None
        v3_auth_url = None
        try:
            ks_discover = discover.Discover(session=session, auth_url=auth_url)
            v2_auth_url = ks_discover.url_for('2.0')
            v3_auth_url = ks_discover.url_for('3.0')
        except ks_exc.ClientException:
            # Identity service may not support discover API version.
            # Lets trying to figure out the API version from the original URL.
            url_parts = urlparse.urlparse(auth_url)
            (scheme, netloc, path, params, query, fragment) = url_parts
            path = path.lower()
            if path.startswith('/v3'):
                v3_auth_url = auth_url
            elif path.startswith('/v2'):
                v2_auth_url = auth_url
            else:
                # not enough information to determine the auth version
                msg = _('Unable to determine the Keystone version '
                        'to authenticate with using the given '
                        'auth_url. Identity service may not support API '
                        'version discovery. Please provide a versioned '
                        'auth_url instead.')
                raise exc.CommandError(msg)

        return (v2_auth_url, v3_auth_url)

    def _get_keystone_session(self, **kwargs):
        # first create a Keystone session
        cacert = kwargs.pop('cacert', None)
        cert = kwargs.pop('cert', None)
        key = kwargs.pop('key', None)
        insecure = kwargs.pop('insecure', False)
        timeout = kwargs.pop('timeout', None)
        verify = kwargs.pop('verify', None)

        # FIXME(gyee): this code should come from keystoneclient
        if verify is None:
            if insecure:
                verify = False
            else:
                # TODO(gyee): should we do
                # heatclient.common.http.get_system_ca_fle()?
                verify = cacert or True
        if cert and key:
            # passing cert and key together is deprecated in favour of the
            # requests lib form of having the cert and key as a tuple
            cert = (cert, key)

        return kssession.Session(verify=verify, cert=cert, timeout=timeout)

    def _get_keystone_v3_auth(self, v3_auth_url, **kwargs):
        auth_token = kwargs.pop('auth_token', None)
        if auth_token:
            return v3_auth.Token(v3_auth_url, auth_token)
        else:
            return v3_auth.Password(v3_auth_url, **kwargs)

    def _get_keystone_v2_auth(self, v2_auth_url, **kwargs):
        auth_token = kwargs.pop('auth_token', None)
        tenant_id = kwargs.pop('project_id', None)
        tenant_name = kwargs.pop('project_name', None)
        if auth_token:
            return v2_auth.Token(v2_auth_url, auth_token,
                                 tenant_id=tenant_id,
                                 tenant_name=tenant_name)
        else:
            return v2_auth.Password(v2_auth_url,
                                    username=kwargs.pop('username', None),
                                    password=kwargs.pop('password', None),
                                    tenant_id=tenant_id,
                                    tenant_name=tenant_name)

    def _get_keystone_auth(self, session, auth_url, **kwargs):
        # FIXME(dhu): this code should come from keystoneclient

        # discover the supported keystone versions using the given url
        (v2_auth_url, v3_auth_url) = self._discover_auth_versions(
            session=session,
            auth_url=auth_url)

        # Determine which authentication plugin to use. First inspect the
        # auth_url to see the supported version. If both v3 and v2 are
        # supported, then use the highest version if possible.
        auth = None
        if v3_auth_url and v2_auth_url:
            user_domain_name = kwargs.get('user_domain_name', None)
            user_domain_id = kwargs.get('user_domain_id', None)
            project_domain_name = kwargs.get('project_domain_name', None)
            project_domain_id = kwargs.get('project_domain_id', None)

            # support both v2 and v3 auth. Use v3 if domain information is
            # provided.
            if (user_domain_name or user_domain_id or project_domain_name or
                    project_domain_id):
                auth = self._get_keystone_v3_auth(v3_auth_url, **kwargs)
            else:
                auth = self._get_keystone_v2_auth(v2_auth_url, **kwargs)
        elif v3_auth_url:
            # support only v3
            auth = self._get_keystone_v3_auth(v3_auth_url, **kwargs)
        elif v2_auth_url:
            # support only v2
            auth = self._get_keystone_v2_auth(v2_auth_url, **kwargs)
        else:
            raise exc.CommandError('Unable to determine the Keystone version '
                                   'to authenticate with using the given '
                                   'auth_url.')

        return auth

    def main(self, argv):
        # Parse args once to find version
        parser = self.get_base_parser()
        (options, args) = parser.parse_known_args(argv)
        self._setup_logging(options.debug)
        self._setup_verbose(options.verbose)

        # build available subcommands based on version
        api_version = options.heat_api_version
        subcommand_parser = self.get_subcommand_parser(api_version)
        self.parser = subcommand_parser

        # Handle top-level --help/-h before attempting to parse
        # a command off the command line
        if not args and options.help or not argv:
            self.do_help(options)
            return 0

        # Parse args again and call whatever callback was selected
        args = subcommand_parser.parse_args(argv)

        # Short-circuit and deal with help command right away.
        if args.func == self.do_help:
            self.do_help(args)
            return 0
        elif args.func == self.do_bash_completion:
            self.do_bash_completion(args)
            return 0

        if not args.os_username and not args.os_auth_token:
            raise exc.CommandError("You must provide a username via"
                                   " either --os-username or env[OS_USERNAME]"
                                   " or a token via --os-auth-token or"
                                   " env[OS_AUTH_TOKEN]")

        if not args.os_password and not args.os_auth_token:
            raise exc.CommandError("You must provide a password via"
                                   " either --os-password or env[OS_PASSWORD]"
                                   " or a token via --os-auth-token or"
                                   " env[OS_AUTH_TOKEN]")

        if args.os_no_client_auth:
            if not args.heat_url:
                raise exc.CommandError("If you specify --os-no-client-auth"
                                       " you must also specify a Heat API URL"
                                       " via either --heat-url or"
                                       " env[HEAT_URL]")
        else:
            # Tenant/project name or ID is needed to make keystoneclient
            # retrieve a service catalog, it's not required if
            # os_no_client_auth is specified, neither is the auth URL

            if not (args.os_tenant_id or args.os_tenant_name or
                    args.os_project_id or args.os_project_name):
                raise exc.CommandError("You must provide a tenant id via"
                                       " either --os-tenant-id or"
                                       " env[OS_TENANT_ID] or a tenant name"
                                       " via either --os-tenant-name or"
                                       " env[OS_TENANT_NAME] or a project id"
                                       " via either --os-project-id or"
                                       " env[OS_PROJECT_ID] or a project"
                                       " name via either --os-project-name or"
                                       " env[OS_PROJECT_NAME]")

            if not args.os_auth_url:
                raise exc.CommandError("You must provide an auth url via"
                                       " either --os-auth-url or via"
                                       " env[OS_AUTH_URL]")

        kwargs = {
            'insecure': args.insecure,
            'cacert': args.os_cacert,
            'cert': args.os_cert,
            'key': args.os_key,
            'timeout': args.api_timeout
        }

        endpoint = args.heat_url
        service_type = args.os_service_type or 'orchestration'
        if args.os_no_client_auth:
            # Do not use session since no_client_auth means using heat to
            # to authenticate
            kwargs = {
                'username': args.os_username,
                'password': args.os_password,
                'auth_url': args.os_auth_url,
                'token': args.os_auth_token,
                'include_pass': args.include_password,
                'insecure': args.insecure,
                'timeout': args.api_timeout
            }
        else:
            keystone_session = self._get_keystone_session(**kwargs)
            project_id = args.os_project_id or args.os_tenant_id
            project_name = args.os_project_name or args.os_tenant_name
            kwargs = {
                'username': args.os_username,
                'user_id': args.os_user_id,
                'user_domain_id': args.os_user_domain_id,
                'user_domain_name': args.os_user_domain_name,
                'password': args.os_password,
                'auth_token': args.os_auth_token,
                'project_id': project_id,
                'project_name': project_name,
                'project_domain_id': args.os_project_domain_id,
                'project_domain_name': args.os_project_domain_name,
            }
            keystone_auth = self._get_keystone_auth(keystone_session,
                                                    args.os_auth_url,
                                                    **kwargs)
            if not endpoint:
                svc_type = service_type
                region_name = args.os_region_name
                endpoint = keystone_auth.get_endpoint(keystone_session,
                                                      service_type=svc_type,
                                                      region_name=region_name)

            endpoint_type = args.os_endpoint_type or 'publicURL'
            kwargs = {
                'auth_url': args.os_auth_url,
                'session': keystone_session,
                'auth': keystone_auth,
                'service_type': service_type,
                'endpoint_type': endpoint_type,
                'region_name': args.os_region_name,
                'username': args.os_username,
                'password': args.os_password,
                'include_pass': args.include_password
            }

        client = heat_client.Client(api_version, endpoint, **kwargs)

        profile = osprofiler_profiler and options.profile
        if profile:
            osprofiler_profiler.init(options.profile)

        args.func(client, args)

        if profile:
            trace_id = osprofiler_profiler.get().get_base_id()
            print("Trace ID: %s" % trace_id)
            print("To display trace use next command:\n"
                  "osprofiler trace show --html %s " % trace_id)

    def do_bash_completion(self, args):
        """Prints all of the commands and options to stdout.

        The heat.bash_completion script doesn't have to hard code them.
        """
        commands = set()
        options = set()
        for sc_str, sc in self.subcommands.items():
            commands.add(sc_str)
            for option in list(sc._optionals._option_string_actions):
                options.add(option)

        commands.remove('bash-completion')
        commands.remove('bash_completion')
        print(' '.join(commands | options))

    @utils.arg('command', metavar='<subcommand>', nargs='?',
               help='Display help for <subcommand>.')
    def do_help(self, args):
        """Display help about this program or one of its subcommands."""
        if getattr(args, 'command', None):
            if args.command in self.subcommands:
                self.subcommands[args.command].print_help()
            else:
                raise exc.CommandError("'%s' is not a valid subcommand" %
                                       args.command)
        else:
            self.parser.print_help()


class HelpFormatter(argparse.HelpFormatter):
    def start_section(self, heading):
        # Title-case the headings
        heading = '%s%s' % (heading[0].upper(), heading[1:])
        super(HelpFormatter, self).start_section(heading)


def main(args=None):
    try:
        if args is None:
            args = sys.argv[1:]

        HeatShell().main(args)
    except KeyboardInterrupt:
        print("... terminating heat client", file=sys.stderr)
        sys.exit(130)
    except Exception as e:
        if '--debug' in args or '-d' in args:
            raise
        else:
            print(strutils.safe_encode(six.text_type(e)), file=sys.stderr)
        sys.exit(1)

if __name__ == "__main__":
    main()
