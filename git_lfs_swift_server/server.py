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
from swiftclient import client
from swiftclient.exceptions import ClientException

from flask import abort, Flask, request

app = Flask(__name__)
app.config.from_envvar('GIT_LFS_SWIFT_SETTINGS_FILE', silent=True)
if 'GIT_LFS_SWIFT_AUTH_URL' in os.environ:
    app.config['AUTH_URL'] = os.environ['GIT_LFS_SWIFT_AUTH_URL']
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


def handle_dl(
        url, token, container, oid, o_size, o_data, expires_at, c_url,
        href):
    """Handle download of object by manipulating o_data dict."""
    try:
        meta = client.head_object(url, token, container, oid)

        if int(meta['content-length']) != o_size:
            o_data['error'] = dict(code=422,
                                   message='Size does not match.')
        else:
            d_action = dict(href=href, header={'x-auth-token': token},
                            expires_at=expires_at)
            o_data['actions'] = {'download': d_action}
    except ClientException as e:
        if e.http_status == 404:
            o_data['error'] = dict(code=404, message='Not found.')
        elif e.http_status == 403:
            abort(403)
        else:
            logger.exception(
                'Failure while heading object with url %s. %s',
                c_url + '/' + oid, str(e))
            abort(500)


def handle_ul(
        url, token, container, oid, o_size, o_data, expires_at, c_url,
        href):
    """Handle upload of object by manipulating o_data dict."""
    try:
        client.head_object(url, token, container, oid)
    except ClientException as e:
        if e.http_status == 404:
            pass
        elif e.http_status == 403:
            # It's possible that a write ACL exist. Test it with a
            # post to a random object, which should not exist.
            try:
                chars = string.ascii_lowercase + string.digits
                obj = '_'.join(random.choice(chars) for x in range(32))
                client.post_object(url, token, container, obj, {})
                # Landing here should be unlikely, but still
                # this would mean that a write is possible.
                pass
            except ClientException as e:
                if e.http_status == 404:
                    # Post is possible, so user has access rights.
                    pass
                elif e.http_status == 403:
                    abort(403)
                else:
                    logger.exception(
                        'Failure while posting dummy object with url '
                        '%s. %s',
                        c_url + '/' + obj, str(e))
                    abort(500)
        else:
            logger.exception(
                'Failure while heading object with url %s. %s',
                c_url + '/' + oid, str(e))
            abort(500)

        # Success. Write action object.
        u_action = dict(href=href,
                        header={'x-auth-token': token},
                        expires_at=expires_at)
        o_data['actions'] = {'upload': u_action}


@app.route('/<account>/<container>/objects/batch', methods=['POST'])
@app.route('/<container>/objects/batch', methods=['POST'])
def batch_api(account=None, container=None):
    """
    Implementation of
    https://github.com/git-lfs/git-lfs/blob/master/docs/api/batch.md.
    """
    auth = request.authorization
    if not auth:
        abort(401)
    try:
        # With this option it should be possible
        # to use keystone auth, too.
        kwargs = app.config.get('AUTH_KWARGS', {})

        url, token = client.get_auth(app.config['AUTH_URL'],
                                     auth.username.replace(';', ':'),
                                     auth.password,
                                     **kwargs)
    except ClientException as e:
        if e.http_status == 401:
            abort(401)
        else:
            abort(500)

    if account:
        # Replace default storage-account.
        url = '/'.join(url.rstrip('/').split('/')[0:-1] + [account])

    expires_in = app.config.get('TOKEN_EXPIRY', 3600)
    expires_at = datetime.fromtimestamp(int(time.time()) +
                                        expires_in, pytz.utc).isoformat()

    data = request.get_json()
    logger.debug('Received Data: %s', data)

    operation = data.get('operation', None)
    if operation not in ('download', 'upload') or 'objects' not in data:
        abort(400)

    # We currently support basic and swift transfer.
    # With swift transfer, the client does also consider LO's.
    if 'swift' in data.get('transfers', []):
        transfer = 'swift'
    else:
        transfer = 'basic'

    c_url = url.rstrip('/') + '/' + container
    objs = []

    if operation == 'download':
        handle = handle_dl
    else:
        handle = handle_ul

    for o in data['objects']:
        try:
            oid = o['oid']
            o_size = o['size']
        except KeyError:
            abort(400)

        o_data = {'oid': oid}
        href = c_url if transfer == 'swift' else c_url + '/' + oid
        handle(
            url, token, container, oid, o_size, o_data, expires_at, c_url,
            href)
        o_data['size'] = o_size
        o_data['authenticated'] = True
        objs.append(o_data)

    result = {'objects': objs, 'transfer': transfer}

    logger.debug('Response %s', result)
    return json.dumps(result), 200, {'Content-Type': 'application/json'}


if __name__ == "__main__":
    if 'AUTH_URL' not in app.config:
        raise Exception('AUTH_URL must be specified.')
    app.run()
