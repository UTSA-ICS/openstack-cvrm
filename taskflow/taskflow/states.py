# -*- coding: utf-8 -*-

#    Copyright (C) 2012-2013 Yahoo! Inc. All Rights Reserved.
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

from taskflow import exceptions as exc

# Job states.
CLAIMED = 'CLAIMED'
COMPLETE = 'COMPLETE'
UNCLAIMED = 'UNCLAIMED'

# Flow states.
FAILURE = 'FAILURE'
PENDING = 'PENDING'
REVERTING = 'REVERTING'
REVERTED = 'REVERTED'
RUNNING = 'RUNNING'
SUCCESS = 'SUCCESS'
SUSPENDING = 'SUSPENDING'
SUSPENDED = 'SUSPENDED'
RESUMING = 'RESUMING'

# Task states (mainly a subset of the flow states).
FAILURE = FAILURE
PENDING = PENDING
REVERTED = REVERTED
REVERTING = REVERTING
SUCCESS = SUCCESS
RUNNING = RUNNING
RETRYING = 'RETRYING'

# Atom intentions.
EXECUTE = 'EXECUTE'
IGNORE = 'IGNORE'
REVERT = 'REVERT'
RETRY = 'RETRY'
INTENTIONS = (EXECUTE, IGNORE, REVERT, RETRY)

# Additional engine states
SCHEDULING = 'SCHEDULING'
WAITING = 'WAITING'
ANALYZING = 'ANALYZING'

# Flow state transitions
# See: http://docs.openstack.org/developer/taskflow/states.html

_ALLOWED_FLOW_TRANSITIONS = frozenset((
    (PENDING, RUNNING),       # run it!

    (RUNNING, SUCCESS),       # all tasks finished successfully
    (RUNNING, FAILURE),       # some of task failed
    (RUNNING, REVERTED),      # some of task failed and flow has been reverted
    (RUNNING, SUSPENDING),    # engine.suspend was called
    (RUNNING, RESUMING),      # resuming from a previous running

    (SUCCESS, RUNNING),       # see note below

    (FAILURE, RUNNING),       # see note below

    (REVERTED, PENDING),      # try again

    (SUSPENDING, SUSPENDED),  # suspend finished
    (SUSPENDING, SUCCESS),    # all tasks finished while we were waiting
    (SUSPENDING, FAILURE),    # some tasks failed while we were waiting
    (SUSPENDING, REVERTED),   # all tasks were reverted while we were waiting
    (SUSPENDING, RESUMING),   # resuming from a previous suspending

    (SUSPENDED, RUNNING),     # restart from suspended

    (RESUMING, SUSPENDED),    # after flow resumed, it is suspended
))


# NOTE(imelnikov) SUCCESS->RUNNING and FAILURE->RUNNING transitions are
# useful when flow or flowdetails backing it were altered after the flow
# was finished; then, client code may want to run through flow again
# to ensure all tasks from updated flow had a chance to run.


# NOTE(imelnikov): Engine cannot transition flow from SUSPENDING to
# SUSPENDED while some tasks from the flow are running and some results
# from them are not retrieved and saved properly, so while flow is
# in SUSPENDING state it may wait for some of the tasks to stop. Then,
# flow can go to SUSPENDED, SUCCESS, FAILURE or REVERTED state depending
# of actual state of the tasks -- e.g. if all tasks were finished
# successfully while we were waiting, flow can be transitioned from
# SUSPENDING to SUCCESS state.

_IGNORED_FLOW_TRANSITIONS = frozenset(
    (a, b)
    for a in (PENDING, FAILURE, SUCCESS, SUSPENDED, REVERTED)
    for b in (SUSPENDING, SUSPENDED, RESUMING)
    if a != b
)


def check_flow_transition(old_state, new_state):
    """Check that flow can transition from old_state to new_state.

    If transition can be performed, it returns True. If transition
    should be ignored, it returns False. If transition is not
    valid, it raises an InvalidState exception.
    """
    if old_state == new_state:
        return False
    pair = (old_state, new_state)
    if pair in _ALLOWED_FLOW_TRANSITIONS:
        return True
    if pair in _IGNORED_FLOW_TRANSITIONS:
        return False
    raise exc.InvalidState("Flow transition from %s to %s is not allowed"
                           % pair)


# Task state transitions
# See: http://docs.openstack.org/developer/taskflow/states.html

_ALLOWED_TASK_TRANSITIONS = frozenset((
    (PENDING, RUNNING),       # run it!

    (RUNNING, SUCCESS),       # the task finished successfully
    (RUNNING, FAILURE),       # the task failed

    (FAILURE, REVERTING),     # task failed, do cleanup now
    (SUCCESS, REVERTING),     # some other task failed, do cleanup now

    (REVERTING, REVERTED),    # revert done
    (REVERTING, FAILURE),     # revert failed

    (REVERTED, PENDING),      # try again

    (SUCCESS, RETRYING),      # retrying retry controller
    (RETRYING, RUNNING),      # run retry controller that has been retrying
))


def check_task_transition(old_state, new_state):
    """Check that task can transition from old_state to new_state.

    If transition can be performed, it returns True, False otherwise.
    """
    pair = (old_state, new_state)
    if pair in _ALLOWED_TASK_TRANSITIONS:
        return True
    return False
