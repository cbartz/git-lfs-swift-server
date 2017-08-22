# coding=utf-8
# Copyright 2017 Christopher Bartz <bartz@dkrz.de>
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

from base64 import b64encode
import json
import unittest

from mock import Mock, patch

from requests import RequestException

from swiftclient.exceptions import ClientException

from git_lfs_swift_server import app


def _request_exc_mock(status_code):
    return Mock(
        raise_for_status=Mock(side_effect=RequestException),
        status_code=status_code)


@patch('time.time', Mock(return_value=0))
@patch('git_lfs_swift_server.server.client.get_auth',
       Mock(return_value=('url', 'token')))
class TestBatchAPI(unittest.TestCase):

    def setUp(self):
        app.config['TESTING'] = True
        app.config['AUTH_URL'] = ''
        self.app = app.test_client()
        self.headers = {
            "Authorization": "Basic {user}".format(
                user=b64encode(b"test_user:test_password")),
            'Content-Type': 'application/json'}

        self.objects = [{'oid': '1', 'size': 1}, {'oid': '2', 'size': 3}]
        self.o1 = lambda op:  {
            'oid': '1', 'size': 1, 'authenticated': True, 'actions':
                {op: {'href': 'url/container/1', 'header':
                    {'x-auth-token': 'token'},
                 'expires_at': '1970-01-01T01:00:00+00:00'}}}
        self.o2 = lambda op: {
            'oid': '2', 'size': 3, 'authenticated': True, 'actions':
                {op: {'href': 'url/container/2', 'header':
                    {'x-auth-token': 'token'},
                 'expires_at': '1970-01-01T01:00:00+00:00'}}}

        self.url = '/container/objects/batch'

    def assert_equal_object(self, o, o_other):
        """ Helper function to avoid the need of setting maxdiff. """
        for k in 'oid', 'size', 'authenticated':
            self.assertIn(k, o)
            self.assertIn(k, o_other)
            self.assertEqual(o[k], o_other[k])
        self.assertEqual(o.get('actions'), o_other.get('actions'))

    def test_invalid_auth(self):
        rv = self.app.post(self.url)
        self.assertEqual(401, rv.status_code)

        with patch('git_lfs_swift_server.server.client.get_auth') as m:
            m.side_effect = ClientException('', http_status=401)
            rv = self.app.post(self.url, headers=self.headers)
            self.assertEqual(401, rv.status_code)

            m.side_effect = ClientException('', http_status=402)
            rv = self.app.post(self.url, headers=self.headers)
            self.assertEqual(500, rv.status_code)

    def test_bad_request(self):
        data = {'operation': 'wrong', 'objects': []}
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

        data = {'operation': 'download'}
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

        data = {'operation': 'upload', 'objects': [{'size': 2}]}
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

        data = {'operation': 'upload', 'objects': [{'oid': '1'}]}
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

    @patch('git_lfs_swift_server.server.requests.head')
    def test_download(self, m):
        data = {'operation': 'download', 'objects': self.objects}

        m.side_effect = [Mock(headers={'content-length': 1}),
                         Mock(headers={'content-length': 3})]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)
        self.assert_equal_object(r_data['objects'][0], self.o1('download'))
        self.assert_equal_object(r_data['objects'][1], self.o2('download'))

        m.side_effect = [
            Mock(headers={'content-length': 4}),
            _request_exc_mock(404)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)
        self.assertEqual(
            r_data['objects'][0],
            {'oid': '1', 'size': 1, 'authenticated': True,
             'error': {'code': 422, 'message': 'Size does not match.'}})
        self.assertEqual(
            r_data['objects'][1],
            {'oid': '2', 'size': 3, 'authenticated': True,
             'error': {'code': 404, 'message': 'Not found.'}})

        m.side_effect = [
            Mock(headers={'content-length': 1}),
            _request_exc_mock(405)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(500, r.status_code)

        m.side_effect = [Mock(headers={'content-length': 1}),
                         _request_exc_mock(403)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(403, r.status_code)

        m.side_effect = [_request_exc_mock(401)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(401, r.status_code)

    @patch('git_lfs_swift_server.server.requests.head')
    @patch('git_lfs_swift_server.server.requests.post')
    def test_upload(self, p_m, h_m):
        data = {'operation': 'upload', 'objects': self.objects}

        h_m.side_effect = [_request_exc_mock(404), _request_exc_mock(404)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)

        self.assert_equal_object(r_data['objects'][0], self.o1('upload'))
        self.assert_equal_object(r_data['objects'][1], self.o2('upload'))

        h_m.side_effect = [Mock(), _request_exc_mock(404)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)
        self.assertEqual(r_data['objects'][0],
                         {'oid': '1', 'size': 1, 'authenticated': True})
        self.assert_equal_object(r_data['objects'][1], self.o2('upload'))

        h_m.side_effect = [Mock(), _request_exc_mock(405)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(500, r.status_code)

        h_m.side_effect = [_request_exc_mock(404), _request_exc_mock(403)]
        p_m.side_effect = [_request_exc_mock(404)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)

        self.assert_equal_object(r_data['objects'][0], self.o1('upload'))
        self.assert_equal_object(r_data['objects'][1], self.o2('upload'))

        h_m.side_effect = [_request_exc_mock(404), _request_exc_mock(403)]
        p_m.side_effect = [_request_exc_mock(403)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(403, r.status_code)

        h_m.side_effect = [_request_exc_mock(404), _request_exc_mock(401)]
        r = self.app.post(self.url,
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(401, r.status_code)

    @patch('git_lfs_swift_server.server.requests.head')
    def test_swift_transfer(self, m):
        data = {'operation': 'upload', 'objects': self.objects,
                'transfers': ['swift', 'basic']}
        m.side_effect = [_request_exc_mock(404), _request_exc_mock(404)]
        r = self.app.post(
            self.url, data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'swift')
        self.assertEqual(len(r_data.get('objects')), 2)
        o1 = self.o1('upload')
        o1['actions']['upload']['href'] = 'url/container'
        o2 = self.o2('upload')
        o2['actions']['upload']['href'] = 'url/container'
        self.assert_equal_object(r_data['objects'][0], o1)
        self.assert_equal_object(r_data['objects'][1], o2)


class TestTempURLBatchAPI(TestBatchAPI):

    def setUp(self):
        super(TestTempURLBatchAPI, self).setUp()
        self.maxDiff = None
        app.config['BASE_URL'] = ''
        self.url = ('/account/container/read_readsig/write_writesig/'
                    '1503324478/objects/batch')
        self.headers = {'Content-Type': 'application/json'}
        self.o1 = lambda op: {
            'oid': '1', 'size': 1, 'authenticated': True, 'actions':
                {op: {'href': '/v1/account/container/1?temp_url_prefix='
                              '&temp_url_sig={}sig&temp_url_expires='
                              '1503324478'.format(
                                'write' if op == 'upload' else 'read'),
                      'header': {},
                 'expires_at': '2017-08-21T14:07:58+00:00'}}}
        self.o2 = lambda op: {
            'oid': '2', 'size': 3, 'authenticated': True, 'actions':
                {op: {'href': '/v1/account/container/2?temp_url_prefix='
                              '&temp_url_sig={}sig&temp_url_expires='
                              '1503324478'.format(
                                'write' if op == 'upload' else 'read'),
                      'header': {},
                 'expires_at': '2017-08-21T14:07:58+00:00'}}}

    @patch('git_lfs_swift_server.server.requests.head')
    def test_swift_transfer(self, m):
        data = {'operation': 'upload', 'objects': self.objects,
                'transfers': ['swift', 'basic']}
        m.side_effect = [_request_exc_mock(404), _request_exc_mock(404)]
        r = self.app.post(
            self.url, data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)
        self.assert_equal_object(r_data['objects'][0], self.o1('upload'))
        self.assert_equal_object(r_data['objects'][1], self.o2('upload'))

    @unittest.skip('tempurl auth will be checked in download/upload')
    def test_invalid_auth(self):
        pass

if __name__ == '__main__':
    unittest.main()
