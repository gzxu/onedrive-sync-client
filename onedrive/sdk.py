# Copyright (C) 2018  XU Guang-zhao
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, only version 3 of the License, but not any
# later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Affero General Public License for more details.
#
# You should have received a copy of the GNU Affero General Public License
# along with this program.  If not, see <https://www.gnu.org/licenses/>.

import os
from collections import OrderedDict
from typing import Callable, Dict, BinaryIO

import requests
from oauthlib.oauth2 import WebApplicationClient
from requests import Session, HTTPError, RequestException
from requests_oauthlib import OAuth2Session

from . import _compare_size
from .algorithms import HASH_ENGINES
from .database import CONFIG, TreeType, load_tree, session_scope, save_tree, ConfigEntity
from .model import Tree, CloudFile, Directory

os.environ['OAUTHLIB_RELAX_TOKEN_SCOPE'] = '1'
MSGRAPH_ENDPOINT = 'https://graph.microsoft.com/v1.0'
CLIENT_ID = '14a374a6-851d-43cc-9da1-7c91fbd02b24'


class BatchClient:
    """
    This client may be difficult to implement because
    operations are relative to other ones and identifiers
    may need to be translated
    """

    def __init__(self, session: Session):
        self._session = session
        self.queue = []

    @property
    def session(self) -> Session:
        return self._session

    def flush(self):
        pass


def get_session(token: Dict = None, token_updater: Callable[[str], None] = None) -> OAuth2Session:
    # WebApplicationClient is used for response_type=code
    client = WebApplicationClient(CLIENT_ID)
    # The protocol of the redirect uri is changed back to https for easy capturing
    # If possible, change the uri to urn:ietf:wg:oauth:2.0:oob
    session = OAuth2Session(
        client=client,
        scope=[
            'Files.ReadWrite',
            'offline_access'
        ],
        redirect_uri='https://login.microsoftonline.com/common/oauth2/nativeclient',
        auto_refresh_url='https://login.microsoftonline.com/common/oauth2/v2.0/token',
        auto_refresh_kwargs={
            'client_id': CLIENT_ID
        },
        token_updater=token_updater,
        token=token
    )
    if token is not None:
        return session
    # Microsoft enforces the response_mode parameter
    authorization_url, state = session.authorization_url(
        'https://login.microsoftonline.com/common/oauth2/v2.0/authorize',
        response_mode='query'
    )
    print('Type the following URL to your browser')
    print(authorization_url)
    print('After you encounter an empty page, paste the URL of that page below')
    code = client.parse_request_uri_response(input('Response: '), state=state)['code']
    # Microsoft enforces the scope parameter
    session.fetch_token('https://login.microsoftonline.com/consumers/oauth2/v2.0/token', code=code, scope=session.scope)
    token_updater(session.token)
    return session


def get_root_id(session: Session) -> str:
    response = session.get(MSGRAPH_ENDPOINT + '/me/drive/root?$select=id')
    response.raise_for_status()
    return response.json()['id']


def upload_large_file_by_parent(session: Session, parent_id: str, name: str, stream: BinaryIO, size: int):
    # The size parameter should only be the real size provided by the filesystem
    response = session.post(MSGRAPH_ENDPOINT + '/me/drive/items/' + parent_id + ':/' + name + ':/createUploadSession')
    response.raise_for_status()
    url = response.json()['uploadUrl']

    bytes_sent = 0
    chunk = None
    while bytes_sent < size:
        try:
            length = min(320 * 1024, size - bytes_sent)
            if not chunk:
                chunk = stream.read(length)
            if len(chunk) != length:
                raise AssertionError()
            response = requests.put(url, data=chunk, headers={'content-range': 'bytes {begin}-{end}/{size}'.format(
                begin=bytes_sent,
                end=bytes_sent + length - 1,
                size=size
            )})
            response.raise_for_status()
            chunk = None
            bytes_sent += length
        except RequestException:
            pass

    response = response.json()
    return file_from_item(response)


def upload_file_by_parent(session: Session, parent_id: str, name: str, stream: BinaryIO):
    response = session.put(
        MSGRAPH_ENDPOINT + '/me/drive/items/' + parent_id + "/children('" + name + "')/content", data=stream
    )
    response.raise_for_status()
    response = response.json()
    return file_from_item(response)


def upload_file_by_id(session: Session, identifier: str, stream: BinaryIO):
    response = session.put(MSGRAPH_ENDPOINT + '/me/drive/items/' + identifier + '/content', data=stream)
    response.raise_for_status()
    response = response.json()
    return file_from_item(response)


def file_from_item(item):
    return CloudFile(
        item['id'],
        item['name'],
        item['parentReference']['id'],
        item['size'],
        item['eTag'],
        item.get('cTag', None),
        item['file']['hashes'] if 'hashes' in item['file'] else {}
    )


def create_dir(session: Session, parent_id: str, name: str) -> str:
    response = session.post(MSGRAPH_ENDPOINT + '/me/drive/items/' + parent_id + '/children', json={
        'name': name,
        'folder': {}
    })
    response.raise_for_status()
    return response.json()['id']


def remove_item(session: Session, identifier: str):
    response = session.delete(MSGRAPH_ENDPOINT + '/me/drive/items/' + identifier)
    response.raise_for_status()


def move_rename_item(session: Session, identifier: str, *, destination_id: str = None, name: str = None):
    request = {}
    if name is not None:
        request['name'] = name
    if destination_id is not None:
        request['parentReference'] = {
            'id': destination_id
        }
    response = session.patch(MSGRAPH_ENDPOINT + '/me/drive/items/' + identifier, json=request)
    response.raise_for_status()


def download_file(session: Session, identifier: str, destination: BinaryIO, size: int, *,
                  checksum: Dict[str, str] = None, timeout: float = 10):
    engines = {algorithm: HASH_ENGINES[algorithm]() for algorithm in checksum if algorithm in HASH_ENGINES}
    for engine in engines.values():
        engine.send(None)

    bytes_read = 0
    url = MSGRAPH_ENDPOINT + '/me/drive/items/' + identifier + '/content?AVOverride=1'
    response = session.get(url, allow_redirects=False)
    response.raise_for_status()
    if response.status_code != 302:
        raise AssertionError('Not a redirecting link')
    url = response.headers['location']

    # As the content is compressed the content-length header is inaccurate
    while True:
        try:
            headers = {'Range': 'bytes=' + str(bytes_read) + '-'} if bytes_read != 0 else {}
            response = requests.get(url, stream=True, headers=headers, timeout=timeout)
            response.raise_for_status()
            for chunk in response.iter_content(chunk_size=None):
                bytes_read += len(chunk)
                # if bytes_read > size:  # The wrong size provided by OneDrive may only be larger
                if False:  # But the size value is forcefully reset to 0
                    raise AssertionError('Read more than expected')
                destination.write(chunk)
                for engine in engines.values():
                    engine.send(chunk)
            if not _compare_size(bytes_read, size):
                raise AssertionError('Size mismatch')
            break

        except RequestException as e:
            print(e)
            pass

    for algorithm, engine in engines.items():
        calculated = engine.send(None)
        expected = checksum[algorithm].upper()
        if calculated != expected:
            raise Exception('Checksum of {algorithm} mismatch, should be {expected}, actually is {actual}'.format(
                algorithm=algorithm,
                expected=expected,
                actual=calculated
            ))


def retrieve_delta(session: Session) -> Tree:
    root_id = getattr(CONFIG, 'root_id', None)
    selects = ','.join([
        'id',
        'name',
        'file',
        'folder',
        'package',
        'deleted',
        'parentReference',
        'eTag',
        'cTag',
        'size'
    ])
    items = OrderedDict()
    delta_link = getattr(CONFIG, 'delta_link', None)

    # TODO: Ugly code below
    url = None
    if delta_link is not None:
        response = session.get(delta_link)
        try:
            response.raise_for_status()
            url = delta_link
            with session_scope() as session:
                tree = load_tree(session, TreeType.DELTA)
        except HTTPError:
            pass

    if url is None:
        if root_id is None:
            root_id = get_root_id(session)
            CONFIG.root_id = root_id
        # The delta link will also contain the $select parameters
        url = MSGRAPH_ENDPOINT + '/me/drive/items/' + root_id + '/delta?$select=' + selects
        tree = Tree(root_id)
        response = session.get(url)
        response.raise_for_status()

    while True:
        response = response.json()
        for item in response['value']:
            identifier = item['id']
            if identifier in items:
                del items[identifier]
            items[identifier] = item
        if '@odata.nextLink' in response:
            url = response['@odata.nextLink']
            response = session.get(url)
            response.raise_for_status()
        elif '@odata.deltaLink' in response:
            new_delta_link = response['@odata.deltaLink']
            break
        else:
            raise Exception('Unexpected response')

    files = tree.files
    dirs = tree.dirs

    deleted = set()
    for identifier, item in items.items():
        if identifier == root_id:
            continue
        if 'deleted' in item:
            if identifier in files:
                del files[identifier]
            else:
                deleted.add(identifier)
        elif 'file' in item:
            files[identifier] = file_from_item(item)
        elif 'folder' in item or 'package' in item:
            dirs[identifier] = Directory(identifier, item['name'], item['parentReference']['id'])

    while True:
        count = False
        for identifier in set(deleted):
            if all(item.parent != identifier for item in list(files.values()) + list(dirs.values())):
                deleted.remove(identifier)
                if identifier in dirs:
                    del dirs[identifier]
                count = True
        if not count:
            break

    tree = Tree(root_id)
    tree.files.update(files)
    tree.dirs.update(dirs)
    tree.reconstruct_by_parents()

    for identifier, file in tree.files.items():
        if file.cTag is None:
            response = session.get(MSGRAPH_ENDPOINT + '/me/drive/items/' + file.id + '?$select=cTag')
            response.raise_for_status()
            file.cTag = response.json()['cTag']

    with session_scope() as session:
        save_tree(session, tree, TreeType.DELTA)
        session.merge(ConfigEntity(key='delta_link', value=new_delta_link))

    return tree
