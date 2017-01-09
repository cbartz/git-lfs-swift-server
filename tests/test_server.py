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

import mock
from swiftclient.exceptions import ClientException

from git_lfs_swift_server import app


@mock.patch('time.time', mock.Mock(return_value=0))
@mock.patch('git_lfs_swift_server.server.client.get_auth',
            mock.Mock(return_value=('url', 'token')))
class BatchAPITestCase(unittest.TestCase):
    def setUp(self):
        app.config['TESTING'] = True
        app.config['AUTH_URL'] = ''
        self.app = app.test_client()
        self.headers = {
            "Authorization": "Basic {user}".format(
                user=b64encode(b"test_user:test_password")),
            'Content-Type': 'application/json'}

        self.objects = [{'oid': '1', 'size': 1}, {'oid': '2', 'size': 3}]
        self.o1 = {
            'oid': '1', 'size': 1, 'authenticated': True, 'actions':
                {'upload': {'href': 'url/container/1', 'header':
                            {'x-auth-token': 'token'},
                 'expires_at': '1970-01-01T01:00:00+00:00'}}}
        self.o2 = {
            'oid': '2', 'size': 3, 'authenticated': True, 'actions':
                {'upload': {'href': 'url/container/2', 'header':
                            {'x-auth-token': 'token'},
                 'expires_at': '1970-01-01T01:00:00+00:00'}}}

    def assert_equal_object(self, o, o_other):
        """ Helper function to avoid the need of setting maxdiff. """
        for k in 'oid', 'size', 'authenticated':
            self.assertIn(k, o)
            self.assertIn(k, o_other)
            self.assertEqual(o[k], o_other[k])
        self.assertEqual(o.get('actions'), o_other.get('actions'))

    def test_invalid_auth(self):
        rv = self.app.post('/container/objects/batch')
        self.assertEqual(401, rv.status_code)

        with mock.patch('git_lfs_swift_server.server.client.get_auth') as m:
            m.side_effect = ClientException('', http_status=401)
            rv = self.app.post("/container/objects/batch",
                               headers=self.headers)
            self.assertEqual(401, rv.status_code)

            m.side_effect = ClientException('', http_status=402)
            rv = self.app.post("/container/objects/batch",
                               headers=self.headers)
            self.assertEqual(500, rv.status_code)

    def test_bad_request(self):
        data = {'operation': 'wrong', 'objects': []}
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

        data = {'operation': 'download'}
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

        data = {'operation': 'upload', 'objects': [{'size': 2}]}
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

        data = {'operation': 'upload', 'objects': [{'oid': '1'}]}
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(400, r.status_code)

    @mock.patch('git_lfs_swift_server.server.client.head_object')
    def test_download(self, m):
        data = {'operation': 'download', 'objects': self.objects}
        self.o1['actions']['download'] = self.o1['actions']['upload']
        del self.o1['actions']['upload']
        self.o2['actions']['download'] = self.o2['actions']['upload']
        del self.o2['actions']['upload']

        m.side_effect = [{'content-length': 1}, {'content-length': 3}]
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)
        self.assert_equal_object(r_data['objects'][0], self.o1)
        self.assert_equal_object(r_data['objects'][1], self.o2)

        m.side_effect = [{'content-length': 2},
                         ClientException('', http_status=404)]
        r = self.app.post('/container/objects/batch',
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

        m.side_effect = [{'content-length': 1},
                         ClientException('', http_status=405)]
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(500, r.status_code)

    @mock.patch('git_lfs_swift_server.server.client.head_object')
    def test_upload(self, m):
        data = {'operation': 'upload', 'objects': self.objects}

        m.side_effect = [ClientException('', http_status=404),
                         ClientException('', http_status=404)]
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)

        self.assert_equal_object(r_data['objects'][0], self.o1)
        self.assert_equal_object(r_data['objects'][1], self.o2)

        m.side_effect = [{}, ClientException('', http_status=404)]
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'basic')
        self.assertEqual(len(r_data.get('objects')), 2)
        self.assertEqual(r_data['objects'][0],
                         {'oid': '1', 'size': 1, 'authenticated': True})
        self.assert_equal_object(r_data['objects'][1], self.o2)

        m.side_effect = [{}, ClientException('', http_status=405)]
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(500, r.status_code)

    @mock.patch('git_lfs_swift_server.server.client.head_object')
    def test_swift_transfer(self, m):
        data = {'operation': 'upload', 'objects': self.objects,
                'transfers': ['swift', 'basic']}
        m.side_effect = [ClientException('', http_status=404),
                         ClientException('', http_status=404)]
        r = self.app.post('/container/objects/batch',
                          data=json.dumps(data), headers=self.headers)
        self.assertEqual(200, r.status_code)
        r_data = json.loads(r.data)
        self.assertEqual(r_data.get('transfer'), 'swift')
        self.assertEqual(len(r_data.get('objects')), 2)
        self.o1['actions']['upload']['href'] = 'url/container'
        self.o2['actions']['upload']['href'] = 'url/container'
        self.assert_equal_object(r_data['objects'][0], self.o1)
        self.assert_equal_object(r_data['objects'][1], self.o2)


if __name__ == '__main__':
    unittest.main()
