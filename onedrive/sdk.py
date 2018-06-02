#!/usr/bin/env python3

# Copyright (C) 2018  XU Guang-zhao
#
# This program is free software: you can redistribute it and/or modify
# it under the terms of the GNU Affero General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
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
from functools import singledispatch
from pathlib import Path
from typing import Callable, Union, Dict, Mapping, Optional

from oauthlib.oauth2 import WebApplicationClient
from requests import Session
from requests_oauthlib import OAuth2Session

from .database import set_config, update_delta_tree
from .local import save_id_in_metadata
from .model import Tree, Operation, AddFile, DelFile, ModifyFile, RenameMoveFile, AddDir, DelDir, RenameMoveDir

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


def upload_file(session: Session, identifier: str, content: Union[str, Path]) -> None:
    content = Path(content)
    with content.open('rb') as file:
        response = session.put(MSGRAPH_ENDPOINT + '/me/drive/items/' + identifier + '/content', data=file)
        response.raise_for_status()


def create_file(session: Session, parent_id: str, name: str, content: Union[str, Path]) -> str:
    content = Path(content)
    with content.open('rb') as file:
        url = MSGRAPH_ENDPOINT + '/me/drive/items/' + parent_id + "/children('" + name + "')/content"
        response = session.put(url, data=file)
        response.raise_for_status()
        return response.json()['id']


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


def download_file(session: Session, identifier: str, path: Union[str, Path], *, checksum: Dict[Callable, str] = None):
    path = Path(path)
    algorithms = {algorithm: algorithm() for algorithm in checksum}
    with path.open('wb') as file:
        response = session.get(MSGRAPH_ENDPOINT + '/me/drive/items/' + identifier + '/content', stream=True)
        response.raise_for_status()
        for chunk in response.iter_content():
            file.write(chunk)
            for algorithm in algorithms:
                algorithms[algorithm].update(chunk)
    for algorithm in algorithms:
        if algorithms[algorithm].hexdigest().upper() != checksum[algorithm].upper():
            raise Exception('Checksum of {algorithm} mismatch, should be {expected}, actually is {actual}'.format(
                algorithm=algorithm,
                expected=checksum[algorithm].upper(),
                actual=algorithms[algorithm].hexdigest().upper()
            ))


def retrieve_delta(session: Session, root_id: str = None) -> Tree:
    items = OrderedDict()
    # delta_link = get_config('delta_link', None)
    delta_link = None  # Force set it to None for bugs TODO
    if delta_link is None:
        selects = ','.join(['id', 'name', 'root', 'file', 'folder', 'parentReference'])
        if root_id is None:
            url = MSGRAPH_ENDPOINT + '/me/drive/root/delta?$select=' + selects
        else:
            # The delta link will also contain the $select parameters
            url = MSGRAPH_ENDPOINT + '/me/drive/items/' + root_id + '/delta?$select=' + selects
    else:
        url = delta_link

    while True:
        response = session.get(url)
        response.raise_for_status()
        response = response.json()
        for item in response['value']:
            identifier = item['id']
            if root_id is None and 'root' in item:
                root_id = identifier
            if identifier in items:
                del items[identifier]
            items[identifier] = item
        if '@odata.nextLink' in response:
            url = response['@odata.nextLink']
        elif '@odata.deltaLink' in response:
            new_delta_link = response['@odata.deltaLink']
            break
        else:
            raise Exception('Unexpected response')

    tree = update_delta_tree(items.values(), root_id)
    set_config('delta_link', new_delta_link)
    return tree


@singledispatch
def cloud_apply_operation(args: Operation, id_to_path: Mapping[str, Path], session: Session) -> str:
    raise NotImplementedError()


@cloud_apply_operation.register(AddFile)
def _(args: AddFile, id_to_path: Mapping[str, Path], session: Session) -> Optional[str]:
    new_id = create_file(session, args.parent_id, args.name, id_to_path[args.child_id])
    save_id_in_metadata(new_id, id_to_path[args.child_id])
    return new_id


@cloud_apply_operation.register(DelFile)
def _(args: DelFile, id_to_path: Mapping[str, Path], session: Session) -> Optional[str]:
    return remove_item(session, args.id)


@cloud_apply_operation.register(ModifyFile)
def _(args: ModifyFile, id_to_path: Mapping[str, Path], session: Session) -> Optional[str]:
    return upload_file(session, args.id, id_to_path[args.id])


@cloud_apply_operation.register(RenameMoveFile)
def _(args: RenameMoveFile, id_to_path: Mapping[str, Path], session: Session) -> Optional[str]:
    return move_rename_item(session, args.id, destination_id=args.destination_id, name=args.name)


@cloud_apply_operation.register(AddDir)
def _(args: AddDir, id_to_path: Mapping[str, Path], session: Session) -> Optional[str]:
    new_id = create_dir(session, args.parent_id, args.name)
    save_id_in_metadata(new_id, id_to_path[args.child_id])
    return new_id


@cloud_apply_operation.register(DelDir)
def _(args: DelDir, id_to_path: Mapping[str, Path], session: Session) -> Optional[str]:
    return remove_item(session, args.id)


@cloud_apply_operation.register(RenameMoveDir)
def _(args: RenameMoveDir, id_to_path: Mapping[str, Path], session: Session) -> Optional[str]:
    return move_rename_item(session, args.id, destination_id=args.destination_id, name=args.name)
