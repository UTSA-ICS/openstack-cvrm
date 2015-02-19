# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or
# implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import base64
import json
from mox3 import mox
import os
import six
from six.moves.urllib import request
import tempfile
import testtools
from testtools.matchers import MatchesRegex
import yaml

from heatclient.common import template_utils
from heatclient import exc


class ShellEnvironmentTest(testtools.TestCase):

    template_a = b'{"heat_template_version": "2013-05-23"}'

    def setUp(self):
        super(ShellEnvironmentTest, self).setUp()
        self.m = mox.Mox()

        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

    def collect_links(self, env, content, url, env_base_url=''):

        jenv = yaml.safe_load(env)
        files = {}
        if url:
            self.m.StubOutWithMock(request, 'urlopen')
            request.urlopen(url).AndReturn(six.BytesIO(content))
            self.m.ReplayAll()

        template_utils.resolve_environment_urls(
            jenv.get('resource_registry'), files, env_base_url)
        if url:
            self.assertEqual(content.decode('utf-8'), files[url])

    def test_process_environment_file(self):

        self.m.StubOutWithMock(request, 'urlopen')
        env_file = '/home/my/dir/env.yaml'
        env = b'''
        resource_registry:
          "OS::Thingy": "file:///home/b/a.yaml"
        '''

        request.urlopen('file://%s' % env_file).AndReturn(
            six.BytesIO(env))
        request.urlopen('file:///home/b/a.yaml').AndReturn(
            six.BytesIO(self.template_a))
        self.m.ReplayAll()

        files, env_dict = template_utils.process_environment_and_files(
            env_file)
        self.assertEqual(
            {'resource_registry': {
                'OS::Thingy': 'file:///home/b/a.yaml'}},
            env_dict)
        self.assertEqual(self.template_a.decode('utf-8'),
                         files['file:///home/b/a.yaml'])

    def test_process_environment_relative_file(self):

        self.m.StubOutWithMock(request, 'urlopen')
        env_file = '/home/my/dir/env.yaml'
        env_url = 'file:///home/my/dir/env.yaml'
        env = b'''
        resource_registry:
          "OS::Thingy": a.yaml
        '''

        request.urlopen(env_url).AndReturn(
            six.BytesIO(env))
        request.urlopen('file:///home/my/dir/a.yaml').AndReturn(
            six.BytesIO(self.template_a))
        self.m.ReplayAll()

        self.assertEqual(
            env_url,
            template_utils.normalise_file_path_to_url(env_file))
        self.assertEqual(
            'file:///home/my/dir',
            template_utils.base_url_for_url(env_url))

        files, env_dict = template_utils.process_environment_and_files(
            env_file)

        self.assertEqual(
            {'resource_registry': {
                'OS::Thingy': 'file:///home/my/dir/a.yaml'}},
            env_dict)
        self.assertEqual(self.template_a.decode('utf-8'),
                         files['file:///home/my/dir/a.yaml'])

    def test_process_environment_relative_file_up(self):

        self.m.StubOutWithMock(request, 'urlopen')
        env_file = '/home/my/dir/env.yaml'
        env_url = 'file:///home/my/dir/env.yaml'
        env = b'''
        resource_registry:
          "OS::Thingy": ../bar/a.yaml
        '''

        request.urlopen(env_url).AndReturn(
            six.BytesIO(env))
        request.urlopen('file:///home/my/bar/a.yaml').AndReturn(
            six.BytesIO(self.template_a))
        self.m.ReplayAll()

        env_url = 'file://%s' % env_file
        self.assertEqual(
            env_url,
            template_utils.normalise_file_path_to_url(env_file))
        self.assertEqual(
            'file:///home/my/dir',
            template_utils.base_url_for_url(env_url))

        files, env_dict = template_utils.process_environment_and_files(
            env_file)

        self.assertEqual(
            {'resource_registry': {
                'OS::Thingy': 'file:///home/my/bar/a.yaml'}},
            env_dict)
        self.assertEqual(self.template_a.decode('utf-8'),
                         files['file:///home/my/bar/a.yaml'])

    def test_process_environment_url(self):
        env = b'''
        resource_registry:
            "OS::Thingy": "a.yaml"
        '''
        url = 'http://no.where/some/path/to/file.yaml'
        tmpl_url = 'http://no.where/some/path/to/a.yaml'

        self.m.StubOutWithMock(request, 'urlopen')
        request.urlopen(url).AndReturn(six.BytesIO(env))
        request.urlopen(tmpl_url).AndReturn(six.BytesIO(self.template_a))
        self.m.ReplayAll()

        files, env_dict = template_utils.process_environment_and_files(
            url)

        self.assertEqual({'resource_registry': {'OS::Thingy': tmpl_url}},
                         env_dict)
        self.assertEqual(self.template_a.decode('utf-8'), files[tmpl_url])

    def test_process_environment_empty_file(self):

        self.m.StubOutWithMock(request, 'urlopen')
        env_file = '/home/my/dir/env.yaml'
        env = b''

        request.urlopen('file://%s' % env_file).AndReturn(six.BytesIO(env))
        self.m.ReplayAll()

        files, env_dict = template_utils.process_environment_and_files(
            env_file)

        self.assertEqual({}, env_dict)
        self.assertEqual({}, files)

    def test_no_process_environment_and_files(self):
        files, env = template_utils.process_environment_and_files()
        self.assertEqual({}, env)
        self.assertEqual({}, files)

    def test_process_multiple_environments_and_files(self):

        self.m.StubOutWithMock(request, 'urlopen')
        env_file1 = '/home/my/dir/env1.yaml'
        env_file2 = '/home/my/dir/env2.yaml'

        env1 = b'''
        parameters:
          "param1": "value1"
        resource_registry:
          "OS::Thingy1": "file:///home/b/a.yaml"
        '''
        env2 = b'''
        parameters:
          "param2": "value2"
        resource_registry:
          "OS::Thingy2": "file:///home/b/b.yaml"
        '''

        request.urlopen('file://%s' % env_file1).AndReturn(
            six.BytesIO(env1))
        request.urlopen('file:///home/b/a.yaml').AndReturn(
            six.BytesIO(self.template_a))
        request.urlopen('file://%s' % env_file2).AndReturn(
            six.BytesIO(env2))
        request.urlopen('file:///home/b/b.yaml').AndReturn(
            six.BytesIO(self.template_a))
        self.m.ReplayAll()

        files, env = template_utils.process_multiple_environments_and_files(
            [env_file1, env_file2])
        self.assertEqual(
            {
                'resource_registry': {
                    'OS::Thingy1': 'file:///home/b/a.yaml',
                    'OS::Thingy2': 'file:///home/b/b.yaml'},
                'parameters': {
                    'param1': 'value1',
                    'param2': 'value2'}
            },
            env)
        self.assertEqual(self.template_a.decode('utf-8'),
                         files['file:///home/b/a.yaml'])
        self.assertEqual(self.template_a.decode('utf-8'),
                         files['file:///home/b/b.yaml'])

    def test_process_multiple_environments_default_resources(self):

        self.m.StubOutWithMock(request, 'urlopen')
        env_file1 = '/home/my/dir/env1.yaml'
        env_file2 = '/home/my/dir/env2.yaml'

        env1 = b'''
        resource_registry:
          resources:
            resource1:
              "OS::Thingy1": "file:///home/b/a.yaml"
            resource2:
              "OS::Thingy2": "file:///home/b/b.yaml"
        '''
        env2 = b'''
        resource_registry:
          resources:
            resource1:
              "OS::Thingy3": "file:///home/b/a.yaml"
            resource2:
              "OS::Thingy4": "file:///home/b/b.yaml"
        '''

        request.urlopen('file://%s' % env_file1).AndReturn(
            six.BytesIO(env1))
        request.urlopen('file:///home/b/a.yaml').InAnyOrder().AndReturn(
            six.BytesIO(self.template_a))
        request.urlopen('file:///home/b/b.yaml').InAnyOrder().AndReturn(
            six.BytesIO(self.template_a))
        request.urlopen('file://%s' % env_file2).AndReturn(
            six.BytesIO(env2))
        request.urlopen('file:///home/b/a.yaml').InAnyOrder().AndReturn(
            six.BytesIO(self.template_a))
        request.urlopen('file:///home/b/b.yaml').InAnyOrder().AndReturn(
            six.BytesIO(self.template_a))
        self.m.ReplayAll()

        files, env = template_utils.process_multiple_environments_and_files(
            [env_file1, env_file2])
        self.assertEqual(
            {
                'resource_registry': {
                    'resources': {
                        'resource1': {
                            'OS::Thingy1': 'file:///home/b/a.yaml',
                            'OS::Thingy3': 'file:///home/b/a.yaml'
                        },
                        'resource2': {
                            'OS::Thingy2': 'file:///home/b/b.yaml',
                            'OS::Thingy4': 'file:///home/b/b.yaml'
                        }
                    }
                }
            },
            env)
        self.assertEqual(self.template_a.decode('utf-8'),
                         files['file:///home/b/a.yaml'])
        self.assertEqual(self.template_a.decode('utf-8'),
                         files['file:///home/b/b.yaml'])

    def test_no_process_multiple_environments_and_files(self):
        files, env = template_utils.process_multiple_environments_and_files()
        self.assertEqual({}, env)
        self.assertEqual({}, files)

    def test_global_files(self):
        url = 'file:///home/b/a.yaml'
        env = '''
        resource_registry:
          "OS::Thingy": "%s"
        ''' % url
        self.collect_links(env, self.template_a, url)

    def test_nested_files(self):
        url = 'file:///home/b/a.yaml'
        env = '''
        resource_registry:
          resources:
            freddy:
              "OS::Thingy": "%s"
        ''' % url
        self.collect_links(env, self.template_a, url)

    def test_http_url(self):
        url = 'http://no.where/container/a.yaml'
        env = '''
        resource_registry:
          "OS::Thingy": "%s"
        ''' % url
        self.collect_links(env, self.template_a, url)

    def test_with_base_url(self):
        url = 'ftp://no.where/container/a.yaml'
        env = '''
        resource_registry:
          base_url: "ftp://no.where/container/"
          resources:
            server_for_me:
              "OS::Thingy": a.yaml
        '''
        self.collect_links(env, self.template_a, url)

    def test_with_built_in_provider(self):
        env = '''
        resource_registry:
          resources:
            server_for_me:
              "OS::Thingy": OS::Compute::Server
        '''
        self.collect_links(env, self.template_a, None)

    def test_with_env_file_base_url_file(self):
        url = 'file:///tmp/foo/a.yaml'
        env = '''
        resource_registry:
          resources:
            server_for_me:
              "OS::Thingy": a.yaml
        '''
        env_base_url = 'file:///tmp/foo'
        self.collect_links(env, self.template_a, url, env_base_url)

    def test_with_env_file_base_url_http(self):
        url = 'http://no.where/path/to/a.yaml'
        env = '''
        resource_registry:
          resources:
            server_for_me:
              "OS::Thingy": to/a.yaml
        '''
        env_base_url = 'http://no.where/path'
        self.collect_links(env, self.template_a, url, env_base_url)

    def test_unsupported_protocol(self):
        env = '''
        resource_registry:
          "OS::Thingy": "sftp://no.where/dev/null/a.yaml"
        '''
        jenv = yaml.safe_load(env)
        fields = {'files': {}}
        self.assertRaises(exc.CommandError,
                          template_utils.get_file_contents,
                          jenv['resource_registry'],
                          fields)


class TestGetTemplateContents(testtools.TestCase):

    def setUp(self):
        super(TestGetTemplateContents, self).setUp()
        self.m = mox.Mox()

        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

    def test_get_template_contents_file(self):
        with tempfile.NamedTemporaryFile() as tmpl_file:
            tmpl = b'{"AWSTemplateFormatVersion" : "2010-09-09",' \
                   b' "foo": "bar"}'
            tmpl_file.write(tmpl)
            tmpl_file.flush()

            files, tmpl_parsed = template_utils.get_template_contents(
                tmpl_file.name)
            self.assertEqual({"AWSTemplateFormatVersion": "2010-09-09",
                              "foo": "bar"}, tmpl_parsed)
            self.assertEqual({}, files)

    def test_get_template_contents_file_empty(self):
        with tempfile.NamedTemporaryFile() as tmpl_file:

            ex = self.assertRaises(
                exc.CommandError,
                template_utils.get_template_contents,
                tmpl_file.name)
            self.assertEqual(
                'Could not fetch template from file://%s' % tmpl_file.name,
                str(ex))

    def test_get_template_contents_file_none(self):
        ex = self.assertRaises(
            exc.CommandError,
            template_utils.get_template_contents)
        self.assertEqual(
            ('Need to specify exactly one of --template-file, '
             '--template-url or --template-object'),
            str(ex))

    def test_get_template_contents_parse_error(self):
        with tempfile.NamedTemporaryFile() as tmpl_file:

            tmpl = b'{"foo": "bar"'
            tmpl_file.write(tmpl)
            tmpl_file.flush()

            ex = self.assertRaises(
                exc.CommandError,
                template_utils.get_template_contents,
                tmpl_file.name)
            self.assertThat(
                str(ex),
                MatchesRegex(
                    'Error parsing template file://%s ' % tmpl_file.name))

    def test_get_template_contents_url(self):
        tmpl = b'{"AWSTemplateFormatVersion" : "2010-09-09", "foo": "bar"}'
        url = 'http://no.where/path/to/a.yaml'
        self.m.StubOutWithMock(request, 'urlopen')
        request.urlopen(url).AndReturn(six.BytesIO(tmpl))
        self.m.ReplayAll()

        files, tmpl_parsed = template_utils.get_template_contents(
            template_url=url)
        self.assertEqual({"AWSTemplateFormatVersion": "2010-09-09",
                          "foo": "bar"}, tmpl_parsed)
        self.assertEqual({}, files)

    def test_get_template_contents_object(self):
        tmpl = '{"AWSTemplateFormatVersion" : "2010-09-09", "foo": "bar"}'
        url = 'http://no.where/path/to/a.yaml'
        self.m.ReplayAll()

        self.object_requested = False

        def object_request(method, object_url):
            self.object_requested = True
            self.assertEqual('GET', method)
            self.assertEqual('http://no.where/path/to/a.yaml', object_url)
            return tmpl

        files, tmpl_parsed = template_utils.get_template_contents(
            template_object=url,
            object_request=object_request)

        self.assertEqual({"AWSTemplateFormatVersion": "2010-09-09",
                          "foo": "bar"}, tmpl_parsed)
        self.assertEqual({}, files)
        self.assertTrue(self.object_requested)

    def check_non_utf8_content(self, filename, content):
        base_url = 'file:///tmp'
        url = '%s/%s' % (base_url, filename)
        template = {'resources':
                    {'one_init':
                     {'type': 'OS::Heat::CloudConfig',
                      'properties':
                      {'cloud_config':
                       {'write_files':
                        [{'path': '/tmp/%s' % filename,
                          'content': {'get_file': url},
                          'encoding': 'b64'}]}}}}}
        self.m.StubOutWithMock(request, 'urlopen')
        raw_content = base64.decodestring(content)
        response = six.BytesIO(raw_content)
        request.urlopen(url).AndReturn(response)
        self.m.ReplayAll()
        files = {}
        template_utils.resolve_template_get_files(
            template, files, base_url)
        self.assertEqual({url: content}, files)
        self.m.VerifyAll()

    def test_get_zip_content(self):
        filename = 'heat.zip'
        content = b'''\
UEsDBAoAAAAAAEZZWkRbOAuBBQAAAAUAAAAIABwAaGVhdC50eHRVVAkAAxRbDVNYh\
t9SdXgLAAEE\n6AMAAATpAwAAaGVhdApQSwECHgMKAAAAAABGWVpEWzgLgQUAAAAF\
AAAACAAYAAAAAAABAAAApIEA\nAAAAaGVhdC50eHRVVAUAAxRbDVN1eAsAAQToAwA\
ABOkDAABQSwUGAAAAAAEAAQBOAAAARwAAAAAA\n'''
        # zip has '\0' in stream
        self.assertIn(b'\0', base64.decodestring(content))
        decoded_content = base64.decodestring(content)
        if six.PY3:
            self.assertRaises(UnicodeDecodeError, decoded_content.decode)
        else:
            self.assertRaises(
                UnicodeDecodeError,
                json.dumps,
                {'content': decoded_content})
        self.check_non_utf8_content(
            filename=filename, content=content)

    def test_get_utf16_content(self):
        filename = 'heat.utf16'
        content = b'//4tTkhTCgA=\n'
        # utf6 has '\0' in stream
        self.assertIn(b'\0', base64.decodestring(content))
        decoded_content = base64.decodestring(content)
        if six.PY3:
            self.assertRaises(UnicodeDecodeError, decoded_content.decode)
        else:
            self.assertRaises(
                UnicodeDecodeError,
                json.dumps,
                {'content': decoded_content})
        self.check_non_utf8_content(filename=filename, content=content)

    def test_get_gb18030_content(self):
        filename = 'heat.gb18030'
        content = b'1tDO5wo=\n'
        # gb18030 has no '\0' in stream
        self.assertNotIn('\0', base64.decodestring(content))
        decoded_content = base64.decodestring(content)
        if six.PY3:
            self.assertRaises(UnicodeDecodeError, decoded_content.decode)
        else:
            self.assertRaises(
                UnicodeDecodeError,
                json.dumps,
                {'content': decoded_content})
        self.check_non_utf8_content(filename=filename, content=content)


class TestTemplateGetFileFunctions(testtools.TestCase):

    hot_template = b'''heat_template_version: 2013-05-23
resources:
  resource1:
    type: OS::type1
    properties:
      foo: {get_file: foo.yaml}
      bar:
        get_file:
          'http://localhost/bar.yaml'
  resource2:
    type: OS::type1
    properties:
      baz:
      - {get_file: baz/baz1.yaml}
      - {get_file: baz/baz2.yaml}
      - {get_file: baz/baz3.yaml}
      ignored_list: {get_file: [ignore, me]}
      ignored_dict: {get_file: {ignore: me}}
      ignored_none: {get_file: }
    '''

    def setUp(self):
        super(TestTemplateGetFileFunctions, self).setUp()
        self.m = mox.Mox()

        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

    def test_hot_template(self):
        self.m.StubOutWithMock(request, 'urlopen')

        tmpl_file = '/home/my/dir/template.yaml'
        url = 'file:///home/my/dir/template.yaml'
        request.urlopen(url).AndReturn(
            six.BytesIO(self.hot_template))
        request.urlopen(
            'http://localhost/bar.yaml').InAnyOrder().AndReturn(
                six.BytesIO(b'bar contents'))
        request.urlopen(
            'file:///home/my/dir/foo.yaml').InAnyOrder().AndReturn(
                six.BytesIO(b'foo contents'))
        request.urlopen(
            'file:///home/my/dir/baz/baz1.yaml').InAnyOrder().AndReturn(
                six.BytesIO(b'baz1 contents'))
        request.urlopen(
            'file:///home/my/dir/baz/baz2.yaml').InAnyOrder().AndReturn(
                six.BytesIO(b'baz2 contents'))
        request.urlopen(
            'file:///home/my/dir/baz/baz3.yaml').InAnyOrder().AndReturn(
                six.BytesIO(b'baz3 contents'))

        self.m.ReplayAll()

        files, tmpl_parsed = template_utils.get_template_contents(
            template_file=tmpl_file)

        self.assertEqual({
            'http://localhost/bar.yaml': b'bar contents',
            'file:///home/my/dir/foo.yaml': b'foo contents',
            'file:///home/my/dir/baz/baz1.yaml': b'baz1 contents',
            'file:///home/my/dir/baz/baz2.yaml': b'baz2 contents',
            'file:///home/my/dir/baz/baz3.yaml': b'baz3 contents',
        }, files)
        self.assertEqual({
            'heat_template_version': '2013-05-23',
            'resources': {
                'resource1': {
                    'type': 'OS::type1',
                    'properties': {
                        'bar': {'get_file': 'http://localhost/bar.yaml'},
                        'foo': {'get_file': 'file:///home/my/dir/foo.yaml'},
                    },
                },
                'resource2': {
                    'type': 'OS::type1',
                    'properties': {
                        'baz': [
                            {'get_file': 'file:///home/my/dir/baz/baz1.yaml'},
                            {'get_file': 'file:///home/my/dir/baz/baz2.yaml'},
                            {'get_file': 'file:///home/my/dir/baz/baz3.yaml'},
                        ],
                        'ignored_list': {'get_file': ['ignore', 'me']},
                        'ignored_dict': {'get_file': {'ignore': 'me'}},
                        'ignored_none': {'get_file': None},
                    },
                }
            }
        }, tmpl_parsed)

    def test_hot_template_outputs(self):
        self.m.StubOutWithMock(request, 'urlopen')
        tmpl_file = '/home/my/dir/template.yaml'
        url = 'file://%s' % tmpl_file
        foo_url = 'file:///home/my/dir/foo.yaml'
        contents = b'''
heat_template_version: 2013-05-23\n\
outputs:\n\
  contents:\n\
    value:\n\
      get_file: foo.yaml\n'''
        request.urlopen(url).AndReturn(six.BytesIO(contents))
        request.urlopen(foo_url).AndReturn(six.BytesIO(b'foo contents'))
        self.m.ReplayAll()
        files = template_utils.get_template_contents(
            template_file=tmpl_file)[0]
        self.assertEqual({foo_url: b'foo contents'}, files)

    def test_hot_template_same_file(self):
        self.m.StubOutWithMock(request, 'urlopen')
        tmpl_file = '/home/my/dir/template.yaml'
        url = 'file://%s' % tmpl_file
        foo_url = 'file:///home/my/dir/foo.yaml'
        contents = b'''
heat_template_version: 2013-05-23\n
outputs:\n\
  contents:\n\
    value:\n\
      get_file: foo.yaml\n\
  template:\n\
    value:\n\
      get_file: foo.yaml\n'''
        request.urlopen(url).AndReturn(six.BytesIO(contents))
        # asserts that is fetched only once even though it is
        # referenced in the template twice
        request.urlopen(foo_url).AndReturn(six.BytesIO(b'foo contents'))
        self.m.ReplayAll()
        files = template_utils.get_template_contents(
            template_file=tmpl_file)[0]
        self.assertEqual({foo_url: b'foo contents'}, files)


class TestTemplateTypeFunctions(testtools.TestCase):

    hot_template = b'''heat_template_version: 2013-05-23
parameters:
  param1:
    type: string
resources:
  resource1:
    type: foo.yaml
    properties:
      foo: bar
  resource2:
    type: OS::Heat::ResourceGroup
    properties:
      resource_def:
        type: spam/egg.yaml
    '''

    foo_template = b'''heat_template_version: "2013-05-23"
parameters:
  foo:
    type: string
    '''

    egg_template = b'''heat_template_version: "2013-05-23"
parameters:
  egg:
    type: string
    '''

    def setUp(self):
        super(TestTemplateTypeFunctions, self).setUp()
        self.m = mox.Mox()

        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

    def test_hot_template(self):
        self.m.StubOutWithMock(request, 'urlopen')
        tmpl_file = '/home/my/dir/template.yaml'
        url = 'file:///home/my/dir/template.yaml'
        request.urlopen(
            'file:///home/my/dir/foo.yaml').InAnyOrder().AndReturn(
                six.BytesIO(self.foo_template))
        request.urlopen(url).InAnyOrder().AndReturn(
            six.BytesIO(self.hot_template))
        request.urlopen(
            'file:///home/my/dir/spam/egg.yaml').InAnyOrder().AndReturn(
                six.BytesIO(self.egg_template))
        self.m.ReplayAll()

        files, tmpl_parsed = template_utils.get_template_contents(
            template_file=tmpl_file)

        self.assertEqual(yaml.load(self.foo_template.decode('utf-8')),
                         json.loads(files.get('file:///home/my/dir/foo.yaml')))
        self.assertEqual(
            yaml.load(self.egg_template.decode('utf-8')),
            json.loads(files.get('file:///home/my/dir/spam/egg.yaml')))

        self.assertEqual({
            u'heat_template_version': u'2013-05-23',
            u'parameters': {
                u'param1': {
                    u'type': u'string'
                }
            },
            u'resources': {
                u'resource1': {
                    u'type': u'file:///home/my/dir/foo.yaml',
                    u'properties': {u'foo': u'bar'}
                },
                u'resource2': {
                    u'type': u'OS::Heat::ResourceGroup',
                    u'properties': {
                        u'resource_def': {
                            u'type': u'file:///home/my/dir/spam/egg.yaml'
                        }
                    }
                }
            }
        }, tmpl_parsed)


class TestNestedIncludes(testtools.TestCase):

    hot_template = b'''heat_template_version: 2013-05-23
parameters:
  param1:
    type: string
resources:
  resource1:
    type: foo.yaml
    properties:
      foo: bar
  resource2:
    type: OS::Heat::ResourceGroup
    properties:
      resource_def:
        type: spam/egg.yaml
      with: {get_file: spam/ham.yaml}
    '''

    egg_template = b'''heat_template_version: 2013-05-23
parameters:
  param1:
    type: string
resources:
  resource1:
    type: one.yaml
    properties:
      foo: bar
  resource2:
    type: OS::Heat::ResourceGroup
    properties:
      resource_def:
        type: two.yaml
      with: {get_file: three.yaml}
    '''

    foo_template = b'''heat_template_version: "2013-05-23"
parameters:
  foo:
    type: string
    '''

    def setUp(self):
        super(TestNestedIncludes, self).setUp()
        self.m = mox.Mox()

        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

    def test_env_nested_includes(self):
        self.m.StubOutWithMock(request, 'urlopen')
        env_file = '/home/my/dir/env.yaml'
        env_url = 'file:///home/my/dir/env.yaml'
        env = b'''
        resource_registry:
          "OS::Thingy": template.yaml
        '''
        template_url = u'file:///home/my/dir/template.yaml'
        foo_url = u'file:///home/my/dir/foo.yaml'
        egg_url = u'file:///home/my/dir/spam/egg.yaml'
        ham_url = u'file:///home/my/dir/spam/ham.yaml'
        one_url = u'file:///home/my/dir/spam/one.yaml'
        two_url = u'file:///home/my/dir/spam/two.yaml'
        three_url = u'file:///home/my/dir/spam/three.yaml'

        request.urlopen(env_url).AndReturn(
            six.BytesIO(env))
        request.urlopen(template_url).AndReturn(
            six.BytesIO(self.hot_template))

        request.urlopen(foo_url).InAnyOrder().AndReturn(
            six.BytesIO(self.foo_template))
        request.urlopen(egg_url).InAnyOrder().AndReturn(
            six.BytesIO(self.egg_template))
        request.urlopen(ham_url).InAnyOrder().AndReturn(
            six.BytesIO(b'ham contents'))
        request.urlopen(one_url).InAnyOrder().AndReturn(
            six.BytesIO(self.foo_template))
        request.urlopen(two_url).InAnyOrder().AndReturn(
            six.BytesIO(self.foo_template))
        request.urlopen(three_url).InAnyOrder().AndReturn(
            six.BytesIO(b'three contents'))
        self.m.ReplayAll()

        files, env_dict = template_utils.process_environment_and_files(
            env_file)

        self.assertEqual(
            {'resource_registry': {
                'OS::Thingy': template_url}},
            env_dict)

        self.assertEqual({
            u'heat_template_version': u'2013-05-23',
            u'parameters': {u'param1': {u'type': u'string'}},
            u'resources': {
                u'resource1': {
                    u'properties': {u'foo': u'bar'},
                    u'type': foo_url
                },
                u'resource2': {
                    u'type': u'OS::Heat::ResourceGroup',
                    u'properties': {
                        u'resource_def': {
                            u'type': egg_url},
                        u'with': {u'get_file': ham_url}
                    }
                }
            }
        }, json.loads(files.get(template_url)))

        self.assertEqual(yaml.load(self.foo_template.decode('utf-8')),
                         json.loads(files.get(foo_url)))
        self.assertEqual({
            u'heat_template_version': u'2013-05-23',
            u'parameters': {u'param1': {u'type': u'string'}},
            u'resources': {
                u'resource1': {
                    u'properties': {u'foo': u'bar'},
                    u'type': one_url},
                u'resource2': {
                    u'type': u'OS::Heat::ResourceGroup',
                    u'properties': {
                        u'resource_def': {u'type': two_url},
                        u'with': {u'get_file': three_url}
                    }
                }
            }
        }, json.loads(files.get(egg_url)))
        self.assertEqual(b'ham contents',
                         files.get(ham_url))
        self.assertEqual(yaml.load(self.foo_template.decode('utf-8')),
                         json.loads(files.get(one_url)))
        self.assertEqual(yaml.load(self.foo_template.decode('utf-8')),
                         json.loads(files.get(two_url)))
        self.assertEqual(b'three contents',
                         files.get(three_url))

        self.m.VerifyAll()


class TestURLFunctions(testtools.TestCase):

    def setUp(self):
        super(TestURLFunctions, self).setUp()
        self.m = mox.Mox()

        self.addCleanup(self.m.VerifyAll)
        self.addCleanup(self.m.UnsetStubs)

    def test_normalise_file_path_to_url_relative(self):
        self.assertEqual(
            'file://%s/foo' % os.getcwd(),
            template_utils.normalise_file_path_to_url(
                'foo'))

    def test_normalise_file_path_to_url_absolute(self):
        self.assertEqual(
            'file:///tmp/foo',
            template_utils.normalise_file_path_to_url(
                '/tmp/foo'))

    def test_normalise_file_path_to_url_file(self):
        self.assertEqual(
            'file:///tmp/foo',
            template_utils.normalise_file_path_to_url(
                'file:///tmp/foo'))

    def test_normalise_file_path_to_url_http(self):
        self.assertEqual(
            'http://localhost/foo',
            template_utils.normalise_file_path_to_url(
                'http://localhost/foo'))

    def test_base_url_for_url(self):
        self.assertEqual(
            'file:///foo/bar',
            template_utils.base_url_for_url(
                'file:///foo/bar/baz'))
        self.assertEqual(
            'file:///foo/bar',
            template_utils.base_url_for_url(
                'file:///foo/bar/baz.txt'))
        self.assertEqual(
            'file:///foo/bar',
            template_utils.base_url_for_url(
                'file:///foo/bar/'))
        self.assertEqual(
            'file:///',
            template_utils.base_url_for_url(
                'file:///'))
        self.assertEqual(
            'file:///',
            template_utils.base_url_for_url(
                'file:///foo'))

        self.assertEqual(
            'http://foo/bar',
            template_utils.base_url_for_url(
                'http://foo/bar/'))
        self.assertEqual(
            'http://foo/bar',
            template_utils.base_url_for_url(
                'http://foo/bar/baz.template'))
