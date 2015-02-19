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

import abc

import six

from taskflow.persistence import logbook


@six.add_metaclass(abc.ABCMeta)
class Backend(object):
    """Base class for persistence backends."""

    def __init__(self, conf):
        if not conf:
            conf = {}
        if not isinstance(conf, dict):
            raise TypeError("Configuration dictionary expected not: %s"
                            % type(conf))
        self._conf = conf

    @abc.abstractmethod
    def get_connection(self):
        """Return a Connection instance based on the configuration settings."""
        pass

    @abc.abstractmethod
    def close(self):
        """Closes any resources this backend has open."""
        pass


@six.add_metaclass(abc.ABCMeta)
class Connection(object):
    """Base class for backend connections."""

    @abc.abstractproperty
    def backend(self):
        """Returns the backend this connection is associated with."""
        pass

    @abc.abstractmethod
    def close(self):
        """Closes any resources this connection has open."""
        pass

    @abc.abstractmethod
    def upgrade(self):
        """Migrate the persistence backend to the most recent version."""
        pass

    @abc.abstractmethod
    def clear_all(self):
        """Clear all entries from this backend."""
        pass

    @abc.abstractmethod
    def validate(self):
        """Validates that a backend is still ok to be used.

        The semantics of this *may* vary depending on the backend. On failure a
        backend specific exception should be raised that will indicate why the
        failure occurred.
        """
        pass

    @abc.abstractmethod
    def update_atom_details(self, atom_detail):
        """Updates a given atom details and returns the updated version.

        NOTE(harlowja): the details that is to be updated must already have
        been created by saving a flow details with the given atom detail inside
        of it.
        """
        pass

    @abc.abstractmethod
    def update_flow_details(self, flow_detail):
        """Updates a given flow details and returns the updated version.

        NOTE(harlowja): the details that is to be updated must already have
        been created by saving a logbook with the given flow detail inside
        of it.
        """
        pass

    @abc.abstractmethod
    def save_logbook(self, book):
        """Saves a logbook, and all its contained information."""
        pass

    @abc.abstractmethod
    def destroy_logbook(self, book_uuid):
        """Deletes/destroys a logbook matching the given uuid."""
        pass

    @abc.abstractmethod
    def get_logbook(self, book_uuid):
        """Fetches a logbook object matching the given uuid."""
        pass

    @abc.abstractmethod
    def get_logbooks(self):
        """Return an iterable of logbook objects."""
        pass


def _format_atom(atom_detail):
    return {
        'atom': atom_detail.to_dict(),
        'type': logbook.atom_detail_type(atom_detail),
    }
