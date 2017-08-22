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

from datetime import datetime
import json
import logging
import os
import random
import string
import time

import pytz
import requests
from swiftclient import client
from swiftclient.exceptions import ClientException

from flask import abort, Flask, request

app = Flask(__name__)
app.config.from_envvar('GIT_LFS_SWIFT_SETTINGS_FILE', silent=True)
if 'GIT_LFS_SWIFT_AUTH_URL' in os.environ:
    app.config['AUTH_URL'] = os.environ['GIT_LFS_SWIFT_AUTH_URL']
if 'GIT_LFS_SWIFT_BASE_URL' in os.environ:
    app.config['BASE_URL'] = os.environ['GIT_LFS_SWIFT_BASE_URL']
if 'GIT_LFS_SWIFT_TOKEN_EXPIRY' in os.environ:
    app.config['TOKEN_EXPIRY'] = os.environ['GIT_LFS_SWIFT_TOKEN_EXPIRY']
if 'GIT_LFS_SWIFT_LOGFILE' in os.environ:
    app.config['LOGFILE'] = os.environ['GIT_LFS_SWIFT_LOGFILE']
if 'GIT_LFS_SWIFT_LOGLEVEL' in os.environ:
    app.config['LOGLEVEL'] = os.environ['GIT_LFS_SWIFT_LOGLEVEL']

if app.config.get('LOGFILE') or app.config.get('LOGLEVEL'):
    loglevel = app.config.get('LOGLEVEL', 'WARNING')
    logging.basicConfig(
        level=loglevel, filename=app.config.get('LOGFILE'),
        format='%(asctime)s [%(name)s] %(levelname)s %(message)s')

logger = logging.getLogger(__name__)


def handle_dl(c_url, oid, query, headers, o_size, o_data):
    """Handle download of object by manipulating o_data dict."""
    url = c_url + '/' + oid + query
    success = False
    r = requests.head(url, headers=headers)
    try:
        r.raise_for_status()
    except requests.RequestException as e:
        if r.status_code == 404:
            o_data['error'] = dict(code=404, message='Not found.')
        elif r.status_code in (401, 403):
            abort(r.status_code)
        else:
            logger.exception(
                'Failure while heading object with url %s. %s',
                url, str(e))
            abort(500)
    else:
        if int(r.headers['content-length']) != o_size:
            o_data['error'] = dict(
                code=422, message='Size does not match.')
        else:
            success = True

    return success


def handle_ul(
        c_url, oid, query, headers, o_size, o_data):
    """Handle upload of object by manipulating o_data dict."""
    url = c_url + '/' + oid + query
    r = requests.head(url, headers=headers)
    try:
        r.raise_for_status()
    except requests.RequestException as e:
        if r.status_code == 404:
            pass
        elif r.status_code == 401:
            abort(401)
        elif r.status_code == 403:
            # It's possible that a write ACL exist. Test it with a
            # post to a random object, which should not exist.
            chars = string.ascii_lowercase + string.digits
            obj = '_'.join(random.choice(chars) for x in range(32))
            url = c_url + '/' + obj
            r = requests.post(url, headers=headers)
            try:
                r.raise_for_status()
                # Landing here should be unlikely, but still
                # this would mean that a write is possible.
                pass
            except requests.RequestException as e:
                if r.status_code == 404:
                    # Post is possible, so user has access rights.
                    pass
                elif r.status_code == 403:
                    abort(403)
                else:
                    logger.exception(
                        'Failure while posting dummy object with url '
                        '%s. %s',
                        url, str(e))
                    abort(500)
        else:
            logger.exception(
                'Failure while heading object with url %s. %s',
                url, str(e))
            abort(500)

        return True


@app.route(
    '/<account>/<container>/read_<readsig>/write_<writesig>/<expires_at>/'
    'objects/batch', methods=['POST'])
@app.route('/<account>/<container>/objects/batch', methods=['POST'])
@app.route('/<container>/objects/batch', methods=['POST'])
def batch_api(
        account=None, container=None, readsig=None, writesig=None,
        expires_at=None):
    """
    Implementation of
    https://github.com/git-lfs/git-lfs/blob/master/docs/api/batch.md.
    """
    auth = request.authorization

    if auth:
        # With this option it should be possible
        # to use keystone auth, too.
        kwargs = app.config.get('AUTH_KWARGS', {})
        try:
            storage_url, token = client.get_auth(
                app.config['AUTH_URL'],
                auth.username.replace(';', ':'),
                auth.password,
                **kwargs)
        except ClientException as e:
            if e.http_status == 401:
                abort(401)
            else:
                abort(500)
        else:
            query = ''
            if account:
                # Replace default storage-account.
                storage_url = '/'.join(
                    storage_url.rstrip('/').split('/')[0:-1] + [account])
    else:
        token = None
        if 'BASE_URL' not in app.config or account is None:
            abort(401)

        storage_url = app.config['BASE_URL'].rstrip('/') + '/v1/' + account

    if not expires_at:
        expires_at_iso = datetime.fromtimestamp(
            int(time.time()) + app.config.get('TOKEN_EXPIRY', 3600),
            pytz.utc).isoformat()
    else:
        expires_at_iso = datetime.fromtimestamp(
            int(expires_at), pytz.utc).isoformat()

    data = request.get_json()
    logger.debug('Received Data: %s', data)

    operation = data.get('operation', None)
    if operation not in ('download', 'upload') or 'objects' not in data:
        abort(400)

    # We currently support basic and swift transfer.
    # With swift transfer, the client does also consider LO's.
    # swift transfer currently only supports token auth.
    if 'swift' in data.get('transfers', []) and token:
        transfer = 'swift'
    else:
        transfer = 'basic'

    c_url = storage_url.rstrip('/') + '/' + container
    objs = []

    if operation == 'download':
        handle = handle_dl
        if not auth:
            query = '?temp_url_prefix=&temp_url_sig={}&temp_url_expires={}'.\
                format(readsig, expires_at)
    else:
        handle = handle_ul
        if not auth:
            query = '?temp_url_prefix=&temp_url_sig={}&temp_url_expires={}'.\
                format(writesig, expires_at)

    for o in data['objects']:
        try:
            oid = o['oid']
            o_size = o['size']
        except KeyError:
            abort(400)

        o_data = {'oid': oid}
        href = c_url if transfer == 'swift' else c_url + '/' + oid + query
        headers = {'x-auth-token': token} if token else {}

        if handle(c_url, oid, query, headers, o_size, o_data):
            action = dict(
                href=href, header=headers, expires_at=expires_at_iso)
            o_data['actions'] = {operation: action}

        o_data['size'] = o_size
        o_data['authenticated'] = True
        objs.append(o_data)

    result = {'objects': objs, 'transfer': transfer}

    logger.debug('Response %s', result)
    return json.dumps(result), 200, {'Content-Type': 'application/json'}


if __name__ == "__main__":
    if 'AUTH_URL' not in app.config and 'BASE_URL' not in app.config:
        raise Exception('AUTH_URL or BASE_URL must be specified.')
    app.run()
