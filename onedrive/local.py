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

import errno
import hashlib
import os
import sys
from collections import defaultdict
from functools import singledispatch
from pathlib import Path
from typing import Iterator, Tuple, Set, Optional, MutableMapping, Mapping

from requests import Session

from .model import Tree, File, Directory, Operation, DelFile, ModifyFile, RenameMoveFile, DelDir, RenameMoveDir
from .model import basic_operation, AddFile, AddDir

if sys.platform == 'linux':
    if 'ONEDRIVE_CONFIG_PATH' in os.environ:
        DATABASE_LOCATION = Path(os.environ['ONEDRIVE_CONFIG_PATH'])
    else:
        Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')).mkdir(parents=True, exist_ok=True)
        DATABASE_LOCATION = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'onedrive.sqlite'
    XATTR_ONEDRIVE_ID = 'user.onedrive.id'


    def save_id_in_metadata(identifier: str, path):
        path = Path(path)
        os.setxattr(str(path), XATTR_ONEDRIVE_ID, identifier.encode())


    def load_id_from_metadata(path) -> Optional[str]:
        path = Path(path)
        try:
            return os.getxattr(str(path), XATTR_ONEDRIVE_ID).decode()
        except OSError as error:
            if error.errno != errno.ENODATA:
                raise
            else:
                return None
else:
    DATABASE_LOCATION = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'onedrive.sqlite'
    raise Exception('Operating system currently unsupported ' + sys.platform)


def _parse_local_tree(path, root_id) -> Tuple[
    Tree,
    MutableMapping[str, str],
    MutableMapping[str, Set[str]],
    MutableMapping[str, Path]
]:
    tree = Tree(root_id)
    counter_to_id = {}
    id_to_counter = defaultdict(set)
    counter_to_path = {}
    path = Path(path)

    def _counter() -> Iterator[str]:
        number = 0
        while True:
            number += 1
            yield '\0' + str(number)

    def _append_children(parent_id: str, counter: Iterator[str], parent_path: Path):
        for child in parent_path.iterdir():
            # Because of duplicated or missing extended attributes, a temporary identifier is applied to every item
            temp_id = next(counter)

            real_id = load_id_from_metadata(child)
            if real_id is not None:
                counter_to_id[temp_id] = real_id
                id_to_counter[real_id].add(temp_id)

            counter_to_path[temp_id] = child
            if child.is_dir():
                basic_operation(AddDir(parent_id, temp_id, child.name), tree)
                _append_children(temp_id, counter, child)
            elif child.is_file():
                sha1 = hashlib.sha1()
                sha1.update(child.read_bytes())
                basic_operation(AddFile(parent_id, temp_id, child.name, sha1.hexdigest().upper()), tree)

    _append_children(tree.root_id, _counter(), path)
    return tree, counter_to_id, id_to_counter, counter_to_path


def _normalize_local_tree(
        local_tree: Tree,
        counter_to_id: MutableMapping[str, str],
        id_to_counter: MutableMapping[str, Set[str]],
        counter_to_path: MutableMapping[str, Path],
        cloud_tree: Tree
) -> Tuple[Tree, MutableMapping[str, Path]]:
    """Remove duplicated identifiers and mark missing ones

    :param local_tree: The tree to be normalized. It will not be changed
    :param counter_to_id: Mapping from temporary identifiers to real ones
    :param id_to_counter: The reverse mapping of @counter_to_id
    :param cloud_tree: The cloud tree for reference in removing duplications
    :return: The resulting tree and a bidirectional map of temporary and real identifiers for normal nodes
    """

    for real_id, temp_ids in id_to_counter.items():
        if len(temp_ids) > 1:
            if real_id in cloud_tree.files:
                cloud_file = cloud_tree.files[real_id]

                def file_compare(temp_file_id: str):
                    temp_file = local_tree.files[temp_file_id]
                    return (
                        temp_file.checksum == cloud_file.checksum,
                        temp_file.parent == cloud_file.parent,
                        temp_file.name == cloud_file.name
                    )

                max_temp_id = max(temp_ids, key=file_compare)
            elif real_id in cloud_tree.dirs:
                cloud_dir = cloud_tree.dirs[real_id]

                def dir_compare(temp_dir_id: str):
                    temp_dir = local_tree.dirs[temp_dir_id]
                    # Perhaps we need to check the content of the directories,
                    # but as this situation is rare, this would not be an urgency
                    return (
                        len(temp_dir.dirs) == len(cloud_dir.dirs),
                        len(temp_dir.files) == len(cloud_dir.files),
                        temp_dir.parent == cloud_dir.parent,
                        temp_dir.name == cloud_dir.name
                    )

                max_temp_id = max(temp_ids, key=dir_compare)
            else:
                raise Exception('Unknown id ' + real_id + ' pretend to be provided by cloud')

            for temp_id in temp_ids:
                if temp_id != max_temp_id:
                    del counter_to_id[temp_id]

    tree = Tree(local_tree.root_id)
    for file_id, file in local_tree.files.items():
        identifier = counter_to_id.get(file_id, file_id)
        new_file = File(identifier, file.name, file.checksum)
        new_file.parent = counter_to_id.get(file.parent, file.parent)
        tree.files[identifier] = new_file
    for dir_id, directory in local_tree.dirs.items():
        if dir_id == tree.root_id:
            continue
        identifier = counter_to_id.get(dir_id, dir_id)
        new_dir = Directory(identifier, directory.name)
        new_dir.parent = counter_to_id.get(directory.parent, directory.parent)
        tree.dirs[identifier] = new_dir

    tree.reconstruct_by_parents()

    id_to_path = {}
    for temp_id, path in counter_to_path.items():
        id_to_path[counter_to_id.get(temp_id, temp_id)] = path

    return tree, id_to_path


def get_local_tree(path, root_id: str, cloud_tree: Tree) -> Tuple[Tree, MutableMapping[str, Path]]:
    path = Path(path)
    tree, counter_to_id, id_to_counter, counter_to_path = _parse_local_tree(path, root_id)
    tree, id_to_path = _normalize_local_tree(tree, counter_to_id, id_to_counter, counter_to_path, cloud_tree)
    id_to_path[root_id] = path
    return tree, id_to_path


@singledispatch
def local_apply_operation(args: Operation, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    raise NotImplementedError()


@local_apply_operation.register(AddFile)
def _(args: AddFile, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    destination = id_to_path[args.parent_id] / args.name
    from onedrive.sdk import download_file
    download_file(session, args.child_id, destination, checksum={hashlib.sha1: args.checksum})
    save_id_in_metadata(args.child_id, destination)
    id_to_path[args.child_id] = destination


@local_apply_operation.register(DelFile)
def _(args: DelFile, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    id_to_path[args.id].unlink()
    del id_to_path[args.id]


@local_apply_operation.register(ModifyFile)
def _(args: ModifyFile, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    from onedrive.sdk import download_file
    download_file(session, args.id, id_to_path[args.id], checksum={hashlib.sha1: args.checksum})


@local_apply_operation.register(RenameMoveFile)
def _(args: RenameMoveFile, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    file = tree.files[args.id]
    destination_id = args.destination_id if args.destination_id is not None else file.parent
    name = args.name if args.name is not None else file.name
    destination = id_to_path[destination_id] / name
    id_to_path[args.id].rename(destination)
    id_to_path[args.id] = destination


@local_apply_operation.register(AddDir)
def _(args: AddDir, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    destination = id_to_path[args.parent_id] / args.name
    destination.mkdir()
    save_id_in_metadata(args.child_id, destination)
    id_to_path[args.child_id] = destination


@local_apply_operation.register(DelDir)
def _(args: DelDir, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    id_to_path[args.id].rmdir()
    del id_to_path[args.id]


@local_apply_operation.register(RenameMoveDir)
def _(args: RenameMoveDir, tree: Tree, id_to_path: MutableMapping[str, Path], session: Session) -> None:
    directory = tree.dirs[args.id]
    destination_id = args.destination_id if args.destination_id is not None else directory.parent
    name = args.name if args.name is not None else directory.name
    destination = id_to_path[destination_id] / name
    current_path = id_to_path[args.id]
    current_path.rename(destination)
    id_to_path[args.id] = destination

    def _migrate(sub_dir_id: str):
        sub_dir = tree.dirs[sub_dir_id]
        for child in sub_dir.files:
            id_to_path[child] = destination / id_to_path[child].relative_to(current_path)
        for child in sub_dir.dirs:
            id_to_path[child] = destination / id_to_path[child].relative_to(current_path)
            _migrate(child)

    _migrate(args.id)


def convert_temp_id(real_id: Mapping[str, str], args: Operation) -> Operation:
    if isinstance(args, AddFile):
        return AddFile(real_id.get(args.parent_id, args.parent_id), args.child_id, args.name, args.checksum)
    if isinstance(args, AddDir):
        return AddDir(real_id.get(args.parent_id, args.parent_id), args.child_id, args.name)
    if isinstance(args, (RenameMoveFile, RenameMoveDir)):
        return type(args)(args.id, args.name, real_id.get(args.destination_id, args.destination_id))
    return args


def register_real_id(new_id: str, args: Operation, real_id: MutableMapping[str, str]) -> Operation:
    if not isinstance(args, (AddFile, AddDir)):
        return args
    if new_id is None:
        raise AssertionError()
    real_id[args.child_id] = new_id
    if isinstance(args, AddFile):
        return AddFile(args.parent_id, new_id, args.name, args.checksum)
    if isinstance(args, AddDir):
        return AddDir(args.parent_id, new_id, args.name)
