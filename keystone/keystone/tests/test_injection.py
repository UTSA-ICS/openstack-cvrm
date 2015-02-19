# Copyright 2012 OpenStack Foundation
#
# Licensed under the Apache License, Version 2.0 (the "License"); you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#      http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.

import testtools
import uuid

from keystone.common import dependency


class TestDependencyInjection(testtools.TestCase):
    def setUp(self):
        super(TestDependencyInjection, self).setUp()
        self.addCleanup(dependency.reset)

    def test_dependency_injection(self):
        class Interface(object):
            def do_work(self):
                assert False

        @dependency.provider('first_api')
        class FirstImplementation(Interface):
            def do_work(self):
                return True

        @dependency.provider('second_api')
        class SecondImplementation(Interface):
            def do_work(self):
                return True

        @dependency.requires('first_api', 'second_api')
        class Consumer(object):
            def do_work_with_dependencies(self):
                assert self.first_api.do_work()
                assert self.second_api.do_work()

        # initialize dependency providers
        first_api = FirstImplementation()
        second_api = SecondImplementation()

        # ... sometime later, initialize a dependency consumer
        consumer = Consumer()

        # the expected dependencies should be available to the consumer
        self.assertIs(consumer.first_api, first_api)
        self.assertIs(consumer.second_api, second_api)
        self.assertIsInstance(consumer.first_api, Interface)
        self.assertIsInstance(consumer.second_api, Interface)
        consumer.do_work_with_dependencies()

    def test_dependency_provider_configuration(self):
        @dependency.provider('api')
        class Configurable(object):
            def __init__(self, value=None):
                self.value = value

            def get_value(self):
                return self.value

        @dependency.requires('api')
        class Consumer(object):
            def get_value(self):
                return self.api.get_value()

        # initialize dependency providers
        api = Configurable(value=True)

        # ... sometime later, initialize a dependency consumer
        consumer = Consumer()

        # the expected dependencies should be available to the consumer
        self.assertIs(consumer.api, api)
        self.assertIsInstance(consumer.api, Configurable)
        self.assertTrue(consumer.get_value())

    def test_dependency_consumer_configuration(self):
        @dependency.provider('api')
        class Provider(object):
            def get_value(self):
                return True

        @dependency.requires('api')
        class Configurable(object):
            def __init__(self, value=None):
                self.value = value

            def get_value(self):
                if self.value:
                    return self.api.get_value()

        # initialize dependency providers
        api = Provider()

        # ... sometime later, initialize a dependency consumer
        consumer = Configurable(value=True)

        # the expected dependencies should be available to the consumer
        self.assertIs(consumer.api, api)
        self.assertIsInstance(consumer.api, Provider)
        self.assertTrue(consumer.get_value())

    def test_inherited_dependency(self):
        class Interface(object):
            def do_work(self):
                assert False

        @dependency.provider('first_api')
        class FirstImplementation(Interface):
            def do_work(self):
                return True

        @dependency.provider('second_api')
        class SecondImplementation(Interface):
            def do_work(self):
                return True

        @dependency.requires('first_api')
        class ParentConsumer(object):
            def do_work_with_dependencies(self):
                assert self.first_api.do_work()

        @dependency.requires('second_api')
        class ChildConsumer(ParentConsumer):
            def do_work_with_dependencies(self):
                assert self.second_api.do_work()
                super(ChildConsumer, self).do_work_with_dependencies()

        # initialize dependency providers
        first_api = FirstImplementation()
        second_api = SecondImplementation()

        # ... sometime later, initialize a dependency consumer
        consumer = ChildConsumer()

        # dependencies should be naturally inherited
        self.assertEqual(
            ParentConsumer._dependencies,
            set(['first_api']))
        self.assertEqual(
            ChildConsumer._dependencies,
            set(['first_api', 'second_api']))
        self.assertEqual(
            consumer._dependencies,
            set(['first_api', 'second_api']))

        # the expected dependencies should be available to the consumer
        self.assertIs(consumer.first_api, first_api)
        self.assertIs(consumer.second_api, second_api)
        self.assertIsInstance(consumer.first_api, Interface)
        self.assertIsInstance(consumer.second_api, Interface)
        consumer.do_work_with_dependencies()

    def test_unresolvable_dependency(self):
        @dependency.requires(uuid.uuid4().hex)
        class Consumer(object):
            pass

        def for_test():
            Consumer()
            dependency.resolve_future_dependencies()

        self.assertRaises(dependency.UnresolvableDependencyException, for_test)

    def test_circular_dependency(self):
        p1_name = uuid.uuid4().hex
        p2_name = uuid.uuid4().hex

        @dependency.provider(p1_name)
        @dependency.requires(p2_name)
        class P1(object):
            pass

        @dependency.provider(p2_name)
        @dependency.requires(p1_name)
        class P2(object):
            pass

        p1 = P1()
        p2 = P2()

        dependency.resolve_future_dependencies()

        self.assertIs(getattr(p1, p2_name), p2)
        self.assertIs(getattr(p2, p1_name), p1)

    def test_reset(self):
        # Can reset the registry of providers.

        p_id = uuid.uuid4().hex

        @dependency.provider(p_id)
        class P(object):
            pass

        p_inst = P()

        self.assertIs(dependency.REGISTRY[p_id], p_inst)

        dependency.reset()

        self.assertFalse(dependency.REGISTRY)

    def test_optional_dependency_not_provided(self):
        requirement_name = uuid.uuid4().hex

        @dependency.optional(requirement_name)
        class C1(object):
            pass

        c1_inst = C1()

        dependency.resolve_future_dependencies()

        self.assertIsNone(getattr(c1_inst, requirement_name))

    def test_optional_dependency_provided(self):
        requirement_name = uuid.uuid4().hex

        @dependency.optional(requirement_name)
        class C1(object):
            pass

        @dependency.provider(requirement_name)
        class P1(object):
            pass

        c1_inst = C1()
        p1_inst = P1()

        dependency.resolve_future_dependencies()

        self.assertIs(getattr(c1_inst, requirement_name), p1_inst)

    def test_optional_and_required(self):
        p1_name = uuid.uuid4().hex
        p2_name = uuid.uuid4().hex
        optional_name = uuid.uuid4().hex

        @dependency.provider(p1_name)
        @dependency.requires(p2_name)
        @dependency.optional(optional_name)
        class P1(object):
            pass

        @dependency.provider(p2_name)
        @dependency.requires(p1_name)
        class P2(object):
            pass

        p1 = P1()
        p2 = P2()

        dependency.resolve_future_dependencies()

        self.assertIs(getattr(p1, p2_name), p2)
        self.assertIs(getattr(p2, p1_name), p1)
        self.assertIsNone(getattr(p1, optional_name))
