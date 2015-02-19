# Copyright 2013 OpenStack Foundation
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

import functools
import uuid

from keystone.common import authorization
from keystone.common import dependency
from keystone.common import driver_hints
from keystone.common import utils
from keystone.common import wsgi
from keystone import config
from keystone import exception
from keystone.openstack.common.gettextutils import _
from keystone.openstack.common import log


LOG = log.getLogger(__name__)
CONF = config.CONF


def v2_deprecated(f):
    """No-op decorator in preparation for deprecating Identity API v2.

    This is a placeholder for the pending deprecation of v2. The implementation
    of this decorator can be replaced with::

        from keystone.openstack.common import versionutils


        v2_deprecated = versionutils.deprecated(
            what='v2 API',
            as_of=versionutils.deprecated.JUNO,
            in_favor_of='v3 API')

    """
    return f


def _build_policy_check_credentials(self, action, context, kwargs):
    LOG.debug(_('RBAC: Authorizing %(action)s(%(kwargs)s)'), {
        'action': action,
        'kwargs': ', '.join(['%s=%s' % (k, kwargs[k]) for k in kwargs])})

    # see if auth context has already been created. If so use it.
    if ('environment' in context and
            authorization.AUTH_CONTEXT_ENV in context['environment']):
        LOG.debug(_('RBAC: using auth context from the request environment'))
        return context['environment'].get(authorization.AUTH_CONTEXT_ENV)

    # now build the auth context from the incoming auth token
    try:
        LOG.debug(_('RBAC: building auth context from the incoming '
                    'auth token'))
        # TODO(ayoung): These two functions return the token in different
        # formats.  However, the call
        # to get_token hits the caching layer, and does not validate the
        # token.  This should be reduced to one call
        if not CONF.token.revoke_by_id:
            self.token_api.token_provider_api.validate_token(
                context['token_id'])
        token_ref = self.token_api.get_token(context['token_id'])
    except exception.TokenNotFound:
        LOG.warning(_('RBAC: Invalid token'))
        raise exception.Unauthorized()

    # NOTE(jamielennox): whilst this maybe shouldn't be within this function
    # it would otherwise need to reload the token_ref from backing store.
    wsgi.validate_token_bind(context, token_ref)

    auth_context = authorization.token_to_auth_context(token_ref['token_data'])

    return auth_context


def protected(callback=None):
    """Wraps API calls with role based access controls (RBAC).

    This handles both the protection of the API parameters as well as any
    target entities for single-entity API calls.

    More complex API calls (for example that deal with several different
    entities) should pass in a callback function, that will be subsequently
    called to check protection for these multiple entities. This callback
    function should gather the appropriate entities needed and then call
    check_proetction() in the V3Controller class.

    """
    def wrapper(f):
        @functools.wraps(f)
        def inner(self, context, *args, **kwargs):
            if 'is_admin' in context and context['is_admin']:
                LOG.warning(_('RBAC: Bypassing authorization'))
            elif callback is not None:
                prep_info = {'f_name': f.__name__,
                             'input_attr': kwargs}
                callback(self, context, prep_info, *args, **kwargs)
            else:
                action = 'identity:%s' % f.__name__
                creds = _build_policy_check_credentials(self, action,
                                                        context, kwargs)

                policy_dict = {}

                # Check to see if we need to include the target entity in our
                # policy checks.  We deduce this by seeing if the class has
                # specified a get_member() method and that kwargs contains the
                # appropriate entity id.
                if (hasattr(self, 'get_member_from_driver') and
                        self.get_member_from_driver is not None):
                    key = '%s_id' % self.member_name
                    if key in kwargs:
                        ref = self.get_member_from_driver(kwargs[key])
                        policy_dict['target'] = {self.member_name: ref}

                # TODO(henry-nash): Move this entire code to a member
                # method inside v3 Auth
                if context.get('subject_token_id') is not None:
                    token_ref = self.token_api.get_token(
                        context['subject_token_id'])
                    policy_dict.setdefault('target', {})
                    policy_dict['target'].setdefault(self.member_name, {})
                    policy_dict['target'][self.member_name]['user_id'] = (
                        token_ref['user_id'])
                    if 'domain' in token_ref['user']:
                        policy_dict['target'][self.member_name].setdefault(
                            'user', {})
                        policy_dict['target'][self.member_name][
                            'user'].setdefault('domain', {})
                        policy_dict['target'][self.member_name]['user'][
                            'domain']['id'] = (
                                token_ref['user']['domain']['id'])

                # Add in the kwargs, which means that any entity provided as a
                # parameter for calls like create and update will be included.
                policy_dict.update(kwargs)
                self.policy_api.enforce(creds,
                                        action,
                                        authorization.flatten(policy_dict))
                LOG.debug(_('RBAC: Authorization granted'))
            return f(self, context, *args, **kwargs)
        return inner
    return wrapper


def filterprotected(*filters):
    """Wraps filtered API calls with role based access controls (RBAC)."""

    def _filterprotected(f):
        @functools.wraps(f)
        def wrapper(self, context, **kwargs):
            if not context['is_admin']:
                action = 'identity:%s' % f.__name__
                creds = _build_policy_check_credentials(self, action,
                                                        context, kwargs)
                # Now, build the target dict for policy check.  We include:
                #
                # - Any query filter parameters
                # - Data from the main url (which will be in the kwargs
                #   parameter) and would typically include the prime key
                #   of a get/update/delete call
                #
                # First  any query filter parameters
                target = dict()
                if filters:
                    for item in filters:
                        if item in context['query_string']:
                            target[item] = context['query_string'][item]

                    LOG.debug(_('RBAC: Adding query filter params (%s)'), (
                        ', '.join(['%s=%s' % (item, target[item])
                                  for item in target])))

                # Now any formal url parameters
                for key in kwargs:
                    target[key] = kwargs[key]

                self.policy_api.enforce(creds,
                                        action,
                                        authorization.flatten(target))

                LOG.debug(_('RBAC: Authorization granted'))
            else:
                LOG.warning(_('RBAC: Bypassing authorization'))
            return f(self, context, filters, **kwargs)
        return wrapper
    return _filterprotected


class V2Controller(wsgi.Application):
    """Base controller class for Identity API v2."""
    def _normalize_domain_id(self, context, ref):
        """Fill in domain_id since v2 calls are not domain-aware.

        This will overwrite any domain_id that was inadvertently
        specified in the v2 call.

        """
        ref['domain_id'] = CONF.identity.default_domain_id
        return ref

    @staticmethod
    def filter_domain_id(ref):
        """Remove domain_id since v2 calls are not domain-aware."""
        ref.pop('domain_id', None)
        return ref

    @staticmethod
    def normalize_username_in_response(ref):
        """Adds username to outgoing user refs to match the v2 spec.

        Internally we use `name` to represent a user's name. The v2 spec
        requires the use of `username` instead.

        """
        if 'username' not in ref and 'name' in ref:
            ref['username'] = ref['name']
        return ref

    @staticmethod
    def normalize_username_in_request(ref):
        """Adds name in incoming user refs to match the v2 spec.

        Internally we use `name` to represent a user's name. The v2 spec
        requires the use of `username` instead.

        """
        if 'name' not in ref and 'username' in ref:
            ref['name'] = ref.pop('username')
        return ref

    @staticmethod
    def v3_to_v2_user(ref):
        """Convert a user_ref from v3 to v2 compatible.

        * v2.0 users are not domain aware, and should have domain_id removed
        * v2.0 users expect the use of tenantId instead of default_project_id
        * v2.0 users have a username attribute

        This method should only be applied to user_refs being returned from the
        v2.0 controller(s).

        If ref is a list type, we will iterate through each element and do the
        conversion.
        """

        def _format_default_project_id(ref):
            """Convert default_project_id to tenantId for v2 calls."""
            default_project_id = ref.pop('default_project_id', None)
            if default_project_id is not None:
                ref['tenantId'] = default_project_id
            elif 'tenantId' in ref:
                # NOTE(morganfainberg): To avoid v2.0 confusion if somehow a
                # tenantId property sneaks its way into the extra blob on the
                # user, we remove it here.  If default_project_id is set, we
                # would override it in either case.
                del ref['tenantId']

        def _normalize_and_filter_user_properties(ref):
            """Run through the various filter/normalization methods."""
            _format_default_project_id(ref)
            V2Controller.filter_domain_id(ref)
            V2Controller.normalize_username_in_response(ref)
            return ref

        if isinstance(ref, dict):
            return _normalize_and_filter_user_properties(ref)
        elif isinstance(ref, list):
            return [_normalize_and_filter_user_properties(x) for x in ref]
        else:
            raise ValueError(_('Expected dict or list: %s') % type(ref))


@dependency.requires('policy_api', 'token_api')
class V3Controller(wsgi.Application):
    """Base controller class for Identity API v3.

    Child classes should set the ``collection_name`` and ``member_name`` class
    attributes, representing the collection of entities they are exposing to
    the API. This is required for supporting self-referential links,
    pagination, etc.

    Class parameters:

    * `_mutable_parameters` - set of parameters that can be changed by users.
                              Usually used by cls.check_immutable_params()
    * `_public_parameters` - set of parameters that are exposed to the user.
                             Usually used by cls.filter_params()

    """

    collection_name = 'entities'
    member_name = 'entity'
    get_member_from_driver = None

    @classmethod
    def base_url(cls, context, path=None):
        endpoint = super(V3Controller, cls).base_url(context, 'public')
        if not path:
            path = cls.collection_name

        return '%s/%s/%s' % (endpoint, 'v3', path.lstrip('/'))

    @classmethod
    def _add_self_referential_link(cls, context, ref):
        ref.setdefault('links', {})
        ref['links']['self'] = cls.base_url(context) + '/' + ref['id']

    @classmethod
    def wrap_member(cls, context, ref):
        cls._add_self_referential_link(context, ref)
        return {cls.member_name: ref}

    @classmethod
    def wrap_collection(cls, context, refs, hints=None):
        """Wrap a collection, checking for filtering and pagination.

        Returns the wrapped collection, which includes:
        - Executing any filtering not already carried out
        - Truncate to a set limit if necessary
        - Adds 'self' links in every member
        - Adds 'next', 'self' and 'prev' links for the whole collection.

        :param context: the current context, containing the original url path
                        and query string
        :param refs: the list of members of the collection
        :param hints: list hints, containing any relevant filters and limit.
                      Any filters already satisfied by managers will have been
                      removed
        """
        # Check if there are any filters in hints that were not
        # handled by the drivers. The driver will not have paginated or
        # limited the output if it found there were filters it was unable to
        # handle.

        if hints is not None:
            refs = cls.filter_by_attributes(refs, hints)

        list_limited, refs = cls.limit(refs, hints)

        for ref in refs:
            cls.wrap_member(context, ref)

        container = {cls.collection_name: refs}
        container['links'] = {
            'next': None,
            'self': cls.base_url(context, path=context['path']),
            'previous': None}

        if list_limited:
            container['truncated'] = True

        return container

    @classmethod
    def limit(cls, refs, hints):
        """Limits a list of entities.

        The underlying driver layer may have already truncated the collection
        for us, but in case it was unable to handle truncation we check here.

        :param refs: the list of members of the collection
        :param hints: hints, containing, among other things, the limit
                      requested

        :returns: boolean indicating whether the list was truncated, as well
                  as the list of (truncated if necessary) entities.

        """
        NOT_LIMITED = False
        LIMITED = True

        if hints is None or hints.get_limit() is None:
            # No truncation was requested
            return NOT_LIMITED, refs

        list_limit = hints.get_limit()
        if list_limit.get('truncated', False):
            # The driver did truncate the list
            return LIMITED, refs

        if len(refs) > list_limit['limit']:
            # The driver layer wasn't able to truncate it for us, so we must
            # do it here
            return LIMITED, refs[:list_limit['limit']]

        return NOT_LIMITED, refs

    @classmethod
    def filter_by_attributes(cls, refs, hints):
        """Filters a list of references by filter values."""

        def _attr_match(ref_attr, val_attr):
            """Matches attributes allowing for booleans as strings.

            We test explicitly for a value that defines it as 'False',
            which also means that the existence of the attribute with
            no value implies 'True'

            """
            if type(ref_attr) is bool:
                return ref_attr == utils.attr_as_boolean(val_attr)
            else:
                return ref_attr == val_attr

        def _inexact_attr_match(filter, ref):
            """Applies an inexact filter to a result dict.

            :param filter: the filter in question
            :param ref: the dict to check

            :returns True if there is a match

            """
            comparator = filter['comparator']
            key = filter['name']

            if key in ref:
                filter_value = filter['value']
                target_value = ref[key]
                if not filter['case_sensitive']:
                    # We only support inexact filters on strings so
                    # it's OK to use lower()
                    filter_value = filter_value.lower()
                    target_value = target_value.lower()

                if comparator == 'contains':
                    return (filter_value in target_value)
                elif comparator == 'startswith':
                    return target_value.startswith(filter_value)
                elif comparator == 'endswith':
                    return target_value.endswith(filter_value)
                else:
                    # We silently ignore unsupported filters
                    return True

            return False

        for filter in hints.filters():
            if filter['comparator'] == 'equals':
                attr = filter['name']
                value = filter['value']
                refs = [r for r in refs if _attr_match(
                    authorization.flatten(r).get(attr), value)]
            else:
                # It might be an inexact filter
                refs = [r for r in refs if _inexact_attr_match(
                    filter, r)]

        return refs

    @classmethod
    def build_driver_hints(cls, context, supported_filters):
        """Build list hints based on the context query string.

        :param context: contains the query_string from which any list hints can
                        be extracted
        :param supported_filters: list of filters supported, so ignore any
                                  keys in query_dict that are not in this list.

        """
        query_dict = context['query_string']
        hints = driver_hints.Hints()

        if query_dict is None:
            return hints

        for key in query_dict:
            # Check if this is an exact filter
            if supported_filters is None or key in supported_filters:
                hints.add_filter(key, query_dict[key])
                continue

            # Check if it is an inexact filter
            for valid_key in supported_filters:
                # See if this entry in query_dict matches a known key with an
                # inexact suffix added.  If it doesn't match, then that just
                # means that there is no inexact filter for that key in this
                # query.
                if not key.startswith(valid_key + '__'):
                    continue

                base_key, comparator = key.split('__', 1)

                # We map the query-style inexact of, for example:
                #
                # {'email__contains', 'myISP'}
                #
                # into a list directive add filter call parameters of:
                #
                # name = 'email'
                # value = 'myISP'
                # comparator = 'contains'
                # case_sensitive = True

                case_sensitive = True
                if comparator.startswith('i'):
                    case_sensitive = False
                    comparator = comparator[1:]
                hints.add_filter(base_key, query_dict[key],
                                 comparator=comparator,
                                 case_sensitive=case_sensitive)

        # NOTE(henry-nash): If we were to support pagination, we would pull any
        # pagination directives out of the query_dict here, and add them into
        # the hints list.
        return hints

    def _require_matching_id(self, value, ref):
        """Ensures the value matches the reference's ID, if any."""
        if 'id' in ref and ref['id'] != value:
            raise exception.ValidationError('Cannot change ID')

    def _require_matching_domain_id(self, ref_id, ref, get_member):
        """Ensure the current domain ID matches the reference one, if any.

        Provided we want domain IDs to be immutable, check whether any
        domain_id specified in the ref dictionary matches the existing
        domain_id for this entity.

        :param ref_id: the ID of the entity
        :param ref: the dictionary of new values proposed for this entity
        :param get_member: The member function to call to get the current
                           entity
        :raises: :class:`keystone.exception.ValidationError`

        """
        # TODO(henry-nash): It might be safer and more efficient to do this
        # check in the managers affected, so look to migrate this check to
        # there in the future.
        if CONF.domain_id_immutable and 'domain_id' in ref:
            existing_ref = get_member(ref_id)
            if ref['domain_id'] != existing_ref['domain_id']:
                raise exception.ValidationError(_('Cannot change Domain ID'))

    def _assign_unique_id(self, ref):
        """Generates and assigns a unique identifer to a reference."""
        ref = ref.copy()
        ref['id'] = uuid.uuid4().hex
        return ref

    def _get_domain_id_for_request(self, context):
        """Get the domain_id for a v3 call."""

        if context['is_admin']:
            return CONF.identity.default_domain_id

        # Fish the domain_id out of the token
        #
        # We could make this more efficient by loading the domain_id
        # into the context in the wrapper function above (since
        # this version of normalize_domain will only be called inside
        # a v3 protected call).  However, this optimization is probably not
        # worth the duplication of state
        try:
            token_ref = self.token_api.get_token(context['token_id'])
        except exception.TokenNotFound:
            LOG.warning(_('Invalid token in _get_domain_id_for_request'))
            raise exception.Unauthorized()

        if 'domain' in token_ref:
            return token_ref['domain']['id']
        else:
            return CONF.identity.default_domain_id

    def _normalize_domain_id(self, context, ref):
        """Fill in domain_id if not specified in a v3 call."""
        if 'domain_id' not in ref:
            ref['domain_id'] = self._get_domain_id_for_request(context)
        return ref

    @staticmethod
    def filter_domain_id(ref):
        """Override v2 filter to let domain_id out for v3 calls."""
        return ref

    def check_protection(self, context, prep_info, target_attr=None):
        """Provide call protection for complex target attributes.

        As well as including the standard parameters from the original API
        call (which is passed in prep_info), this call will add in any
        additional entities or attributes (passed in target_attr), so that
        they can be referenced by policy rules.

         """
        if 'is_admin' in context and context['is_admin']:
            LOG.warning(_('RBAC: Bypassing authorization'))
        else:
            action = 'identity:%s' % prep_info['f_name']
            # TODO(henry-nash) need to log the target attributes as well
            creds = _build_policy_check_credentials(self, action,
                                                    context,
                                                    prep_info['input_attr'])
            # Build the dict the policy engine will check against from both the
            # parameters passed into the call we are protecting (which was
            # stored in the prep_info by protected()), plus the target
            # attributes provided.
            policy_dict = {}
            if target_attr:
                policy_dict = {'target': target_attr}
            policy_dict.update(prep_info['input_attr'])
            self.policy_api.enforce(creds,
                                    action,
                                    authorization.flatten(policy_dict))
            LOG.debug(_('RBAC: Authorization granted'))

    @classmethod
    def check_immutable_params(cls, ref):
        """Raise exception when disallowed parameter is in ref.

        Check whether the ref dictionary representing a request has only
        mutable parameters included. If not, raise an exception. This method
        checks only root-level keys from a ref dictionary.

        :param ref: a dictionary representing deserialized request to be
                    stored
        :raises: :class:`keystone.exception.ImmutableAttributeError`

        """
        ref_keys = set(ref.keys())
        blocked_keys = ref_keys.difference(cls._mutable_parameters)

        if not blocked_keys:
            #No immutable parameters changed
            return

        exception_args = {'target': cls.__name__,
                          'attribute': blocked_keys.pop()}
        raise exception.ImmutableAttributeError(**exception_args)

    @classmethod
    def check_required_params(cls, ref):
        """Raise exception when required parameter is not in ref.

        Check whether the ref dictionary representing a request has the
        required parameters to fulfill the request. If not, raise an
        exception. This method checks only root-level keys from a ref
        dictionary.

        :param ref: a dictionary representing deserialized request to be
                    stored
        :raises: :class:`keystone.exception.ValidationError`

        """
        ref_keys = set(ref.keys())
        missing_args = []

        for required in cls._required_parameters:
            if required not in ref_keys:
                missing_args.append(required)

        if len(missing_args) > 0:
            exception_args = {'target': cls.__name__,
                              'attribute': missing_args.pop()}
            raise exception.ValidationError(**exception_args)
        else:
            return

    @classmethod
    def filter_params(cls, ref):
        """Remove unspecified parameters from the dictionary.

        This function removes unspecified parameters from the dictionary. See
        check_immutable_parameters for corresponding function that raises
        exceptions. This method checks only root-level keys from a ref
        dictionary.

        :param ref: a dictionary representing deserialized response to be
                    serialized
        """
        ref_keys = set(ref.keys())
        blocked_keys = ref_keys - cls._public_parameters
        for blocked_param in blocked_keys:
            del ref[blocked_param]
        return ref
