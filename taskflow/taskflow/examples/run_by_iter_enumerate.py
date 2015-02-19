# -*- coding: utf-8 -*-

#    Copyright (C) 2014 Yahoo! Inc. All Rights Reserved.
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

import logging
import os
import sys

logging.basicConfig(level=logging.ERROR)

self_dir = os.path.abspath(os.path.dirname(__file__))
top_dir = os.path.abspath(os.path.join(os.path.dirname(__file__),
                                       os.pardir,
                                       os.pardir))
sys.path.insert(0, top_dir)
sys.path.insert(0, self_dir)

from taskflow import engines
from taskflow.patterns import linear_flow as lf
from taskflow.persistence import backends as persistence_backends
from taskflow import task
from taskflow.utils import persistence_utils

# INTRO: This examples shows how to run a engine using the engine iteration
# capability, in between iterations other activities occur (in this case a
# value is output to stdout); but more complicated actions can occur at the
# boundary when a engine yields its current state back to the caller.


class EchoNameTask(task.Task):
    def execute(self):
        print(self.name)


f = lf.Flow("counter")
for i in range(0, 10):
    f.add(EchoNameTask("echo_%s" % (i + 1)))

be = persistence_backends.fetch(conf={'connection': 'memory'})
book = persistence_utils.temporary_log_book(be)
fd = persistence_utils.create_flow_detail(f, book, be)
e = engines.load(f, flow_detail=fd, backend=be, book=book)
e.compile()
e.prepare()

for i, st in enumerate(e.run_iter(), 1):
    print("Transition %s: %s" % (i, st))
