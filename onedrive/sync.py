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

import json
import logging
import time
from enum import Enum
from functools import singledispatch
from pathlib import Path
from typing import Mapping, MutableMapping, Sequence

from requests import Session

from . import _compare_size
from .algorithms import get_change_set, check_same_node_operations, mark_dependencies, topological_sort, field_test
from .algorithms import optimize_cloud_deletion, compare_file_by_cTag, compare_file_by_mtime, compare_file_by_hashes
from .database import CONFIG, TreeType, session_scope, load_tree, save_tree, ConfigEntity
from .local import get_local_tree
from .model import RenameMoveDir, Tree, AddCloudFile, ModifyCloudFile
from .model import basic_operation, Operation, AddFile, DelFile, ModifyFile, RenameMoveFile, AddDir, DelDir
from .platform import save_id_in_metadata
from .sdk import get_session, retrieve_delta
from .sdk import remove_item, move_rename_item, create_dir, download_file, upload_large_file_by_parent


class SyncDirection(Enum):
    TWO_WAY = 0
    DOWNLOAD_ONLY = 1
    UPLOAD_ONLY = 2


def sync(direction: SyncDirection) -> int:
    token = getattr(CONFIG, 'token', None)
    token = json.loads(token) if token is not None else None
    sdk_session = get_session(token, lambda new_token: setattr(CONFIG, 'token', json.dumps(new_token)))

    logging.info('Retrieving cloud tree structure')
    cloud_tree = retrieve_delta(sdk_session)
    logging.info('Cloud tree structure retrieved successfully')

    logging.info('Loading previous state from database')
    with session_scope() as db_session:
        saved_tree = load_tree(db_session, TreeType.SAVED)
    logging.info('Previous state loaded successfully')

    logging.info('Parsing local tree structure')
    local_tree, id_to_path = get_local_tree(CONFIG.local_path, cloud_tree)
    logging.info('Local tree structure parsed successfully')

    logging.info('Comparing trees and generating operations')

    last_sync_time = int(getattr(CONFIG, 'last_sync_time', 0))
    if direction == SyncDirection.TWO_WAY:
        cloud_changes = get_change_set(saved_tree, cloud_tree, compare_file_by_cTag)
        local_changes = get_change_set(saved_tree, local_tree, compare_file_by_mtime(last_sync_time))

        check_same_node_operations(cloud_changes, local_changes)

        cloud_dependencies = mark_dependencies(saved_tree, cloud_changes)
        local_dependencies = mark_dependencies(saved_tree, local_changes)

        cloud_script = topological_sort(cloud_changes, cloud_dependencies)
        local_script = topological_sort(local_changes, local_dependencies)

        if not field_test(saved_tree, cloud_script).equals(cloud_tree):
            raise AssertionError()
        if not field_test(saved_tree, local_script).equals(local_tree):
            raise AssertionError()

        cloud_final = field_test(cloud_tree, local_script)
        local_final = field_test(local_tree, cloud_script)
        if not cloud_final.equals(local_final):
            raise AssertionError()

        local_script = optimize_cloud_deletion(saved_tree, local_script)
    elif direction == SyncDirection.DOWNLOAD_ONLY:
        cloud_changes = get_change_set(local_tree, cloud_tree, compare_file_by_hashes(id_to_path))

        cloud_dependencies = mark_dependencies(local_tree, cloud_changes)

        cloud_script = topological_sort(cloud_changes, cloud_dependencies)
        local_script = []

        if not field_test(local_tree, cloud_script).equals(cloud_tree):
            raise AssertionError()
    elif direction == SyncDirection.UPLOAD_ONLY:
        local_changes = get_change_set(cloud_tree, local_tree, compare_file_by_mtime(last_sync_time))

        local_dependencies = mark_dependencies(cloud_tree, local_changes)

        cloud_script = []
        local_script = topological_sort(local_changes, local_dependencies)

        optimize_cloud_deletion(saved_tree, local_script)

        if not field_test(cloud_tree, local_script).equals(local_tree):
            raise AssertionError()
    else:
        raise AssertionError()

    logging.info('Compared successfully')
    if not cloud_script:
        logging.info('No operations need to be applied locally')
    else:
        logging.info('Applying these operations locally:')
        for line in cloud_script:
            logging.info(str(line))
    if not local_script:
        logging.info('No operations need to be applied to the cloud')
    else:
        logging.info('Applying these operations to the cloud:')
        for line in local_script:
            logging.info(str(line))

    if cloud_script or local_script:
        while True:
            confirm = input('Proceed? [Y/n] ')
            confirm = confirm.lower()
            if confirm == '' or confirm == 'y':
                break
            if confirm == 'n':
                logging.info('Cancelled')
                return -1

        local_apply_script(cloud_script, id_to_path, local_tree, cloud_tree, sdk_session)
        cloud_apply_script(local_script, id_to_path, local_tree, cloud_tree, sdk_session)

    with session_scope() as db_session:
        save_tree(db_session, cloud_tree, TreeType.SAVED)
        db_session.merge(ConfigEntity(key='last_sync_time', value=str(int(time.time() * 1e9))))

    return 0


def local_apply_script(
        cloud_script: Sequence[Operation],
        id_to_path: MutableMapping[str, Path],
        local_tree: Tree,
        cloud_tree: Tree,
        session: Session
):
    for index, line in enumerate(cloud_script):
        logging.info('Applying to local state (' + str(index + 1) + '/' + str(len(cloud_script)) + ')')
        local_apply_operation(line, local_tree, cloud_tree, id_to_path, session)
        basic_operation(line, local_tree)


@singledispatch
def local_apply_operation(
        args: Operation,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    raise NotImplementedError()


@local_apply_operation.register(AddFile)
def _(
        args: AddFile,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    destination = id_to_path[args.parent_id] / args.name
    cloud_file = cloud_tree.files[args.child_id]
    with destination.open('wb') as file:
        download_file(session, args.child_id, file, cloud_file.size, checksum=cloud_file.hashes)
    save_id_in_metadata(args.child_id, destination)
    id_to_path[args.child_id] = destination


@local_apply_operation.register(DelFile)
def _(
        args: DelFile,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    id_to_path[args.id].unlink()
    del id_to_path[args.id]


@local_apply_operation.register(ModifyFile)
def _(
        args: ModifyFile,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    cloud_file = cloud_tree.files[args.id]
    with id_to_path[args.id].open('wb') as file:
        download_file(session, args.id, file, cloud_file.size, checksum=cloud_file.hashes)


@local_apply_operation.register(RenameMoveFile)
def _(
        args: RenameMoveFile,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    file = local_tree.files[args.id]
    destination_id = args.destination_id if args.destination_id is not None else file.parent
    name = args.name if args.name is not None else file.name
    destination = id_to_path[destination_id] / name
    id_to_path[args.id].rename(destination)
    id_to_path[args.id] = destination


@local_apply_operation.register(AddDir)
def _(
        args: AddDir,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    destination = id_to_path[args.parent_id] / args.name
    destination.mkdir()
    save_id_in_metadata(args.child_id, destination)
    id_to_path[args.child_id] = destination


@local_apply_operation.register(DelDir)
def _(
        args: DelDir,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    id_to_path[args.id].rmdir()
    del id_to_path[args.id]


@local_apply_operation.register(RenameMoveDir)
def _(
        args: RenameMoveDir,
        local_tree: Tree,
        cloud_tree: Tree,
        id_to_path: MutableMapping[str, Path],
        session: Session
) -> None:
    directory = local_tree.dirs[args.id]
    destination_id = args.destination_id if args.destination_id is not None else directory.parent
    name = args.name if args.name is not None else directory.name
    destination = id_to_path[destination_id] / name
    current_path = id_to_path[args.id]
    current_path.rename(destination)
    id_to_path[args.id] = destination

    def _migrate(sub_dir_id: str):
        sub_dir = local_tree.dirs[sub_dir_id]
        for child in sub_dir.files:
            id_to_path[child] = destination / id_to_path[child].relative_to(current_path)
        for child in sub_dir.dirs:
            id_to_path[child] = destination / id_to_path[child].relative_to(current_path)
            _migrate(child)

    _migrate(args.id)


def cloud_apply_script(
        local_script: Sequence[Operation],
        id_to_path: Mapping[str, Path],
        local_tree: Tree,
        cloud_tree: Tree,
        session: Session
):
    real_id = {}
    for index, line in enumerate(local_script):
        logging.info('Applying to cloud state (' + str(index + 1) + '/' + str(len(local_script)) + ')')
        line = cloud_apply_operation(line, cloud_tree, id_to_path, real_id, session)
        basic_operation(line, cloud_tree)


@singledispatch
def cloud_apply_operation(
        args: Operation,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    raise NotImplementedError()


@cloud_apply_operation.register(AddFile)
def _(
        args: AddFile,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    parent_id = real_id.get(args.parent_id, args.parent_id)
    path = id_to_path[args.child_id]
    if not _compare_size(path.stat().st_size, args.size):
        raise AssertionError()
    with path.open('rb') as file:
        new_file = upload_large_file_by_parent(session, parent_id, args.name, file, path.stat().st_size)
    save_id_in_metadata(new_file.id, path)
    real_id[args.child_id] = new_file.id
    return AddCloudFile(parent_id, new_file.id, args.name, args.size, new_file.eTag, new_file.cTag)


@cloud_apply_operation.register(DelFile)
def _(
        args: DelFile,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    remove_item(session, args.id)
    return args


@cloud_apply_operation.register(ModifyFile)
def _(
        args: ModifyFile,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    orig_file = cloud_tree.files[args.id]
    path = id_to_path[args.id]
    if not _compare_size(path.stat().st_size, args.size):
        raise AssertionError()
    with path.open('rb') as file:
        new_file = upload_large_file_by_parent(session, orig_file.parent, orig_file.name, file, path.stat().st_size)
    return ModifyCloudFile(args.id, args.size, new_file.eTag, new_file.cTag)


@cloud_apply_operation.register(RenameMoveFile)
def _(
        args: RenameMoveFile,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    destination_id = real_id.get(args.destination_id, args.destination_id)
    move_rename_item(session, args.id, destination_id=destination_id, name=args.name)
    return RenameMoveFile(args.id, args.name, destination_id)


@cloud_apply_operation.register(AddDir)
def _(
        args: AddDir,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    parent_id = real_id.get(args.parent_id, args.parent_id)
    new_id = create_dir(session, parent_id, args.name)
    save_id_in_metadata(new_id, id_to_path[args.child_id])
    real_id[args.child_id] = new_id
    return AddDir(parent_id, new_id, args.name)


@cloud_apply_operation.register(DelDir)
def _(
        args: DelDir,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    remove_item(session, args.id)
    return args


@cloud_apply_operation.register(RenameMoveDir)
def _(
        args: RenameMoveDir,
        cloud_tree: Tree,
        id_to_path: Mapping[str, Path],
        real_id: MutableMapping[str, str],
        session: Session
) -> Operation:
    destination_id = real_id.get(args.destination_id, args.destination_id)
    move_rename_item(session, args.id, destination_id=destination_id, name=args.name)
    return RenameMoveFile(args.id, args.name, destination_id)
