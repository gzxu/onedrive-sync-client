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

from collections import defaultdict
from pathlib import Path
from typing import Iterator, Tuple, Set, MutableMapping, Mapping

from . import _compare_size
from .database import CONFIG
from .model import AddFile, AddDir, CloudFile, AddCloudFile
from .model import Tree, Directory, Operation, RenameMoveFile, RenameMoveDir, LocalFile
from .platform import load_id_from_metadata


def _parse_local_tree(path) -> Tuple[
    Tree,
    MutableMapping[str, str],
    MutableMapping[str, Set[str]],
    MutableMapping[str, Path]
]:
    tree = Tree(CONFIG.root_id)
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
                tree.dirs[temp_id] = Directory(temp_id, child.name, parent_id)
                tree.dirs[parent_id].dirs.add(temp_id)
                _append_children(temp_id, counter, child)
            elif child.is_file():
                stat = child.stat()
                tree.files[temp_id] = LocalFile(temp_id, child.name, parent_id, stat.st_size, stat.st_mtime_ns)
                tree.dirs[parent_id].files.add(temp_id)

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
                        _compare_size(temp_file.size, cloud_file.size),
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
        tree.files[identifier] = LocalFile(identifier, file.name, counter_to_id.get(
            file.parent, file.parent
        ), file.size, file.st_mtime_ns)
    for dir_id, directory in local_tree.dirs.items():
        if dir_id == tree.root_id:
            continue
        identifier = counter_to_id.get(dir_id, dir_id)
        tree.dirs[identifier] = Directory(identifier, directory.name, counter_to_id.get(
            directory.parent, directory.parent
        ))

    tree.reconstruct_by_parents()

    id_to_path = {}
    for temp_id, path in counter_to_path.items():
        id_to_path[counter_to_id.get(temp_id, temp_id)] = path

    return tree, id_to_path


def get_local_tree(path, cloud_tree: Tree) -> Tuple[Tree, MutableMapping[str, Path]]:
    path = Path(path)
    tree, counter_to_id, id_to_counter, counter_to_path = _parse_local_tree(path)
    tree, id_to_path = _normalize_local_tree(tree, counter_to_id, id_to_counter, counter_to_path, cloud_tree)
    id_to_path[CONFIG.root_id] = path
    return tree, id_to_path


def convert_temp_id(real_id: Mapping[str, str], args: Operation) -> Operation:
    if isinstance(args, AddFile):
        return AddFile(real_id.get(args.parent_id, args.parent_id), args.child_id, args.name, args.size)
    if isinstance(args, AddDir):
        return AddDir(real_id.get(args.parent_id, args.parent_id), args.child_id, args.name)
    if isinstance(args, (RenameMoveFile, RenameMoveDir)):
        return type(args)(args.id, args.name, real_id.get(args.destination_id, args.destination_id))
    return args


def register_real_id(new_file: CloudFile, args: Operation, real_id: MutableMapping[str, str]) -> Operation:
    if not isinstance(args, (AddFile, AddDir)):
        return args
    if new_file is None:
        raise AssertionError()
    real_id[args.child_id] = new_file.id
    if isinstance(args, AddFile):
        return AddCloudFile(args.parent_id, new_file.id, args.name, args.size, new_file.eTag, new_file.cTag)
    if isinstance(args, AddDir):
        return AddDir(args.parent_id, new_file.id, args.name)
