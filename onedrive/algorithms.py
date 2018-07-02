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

import copy
import hashlib
import itertools
import zlib
from collections import defaultdict
from functools import singledispatch
from pathlib import Path
from typing import Set, Tuple, Sequence, Optional, Callable, Mapping

import attr

from . import _compare_size
from .model import Operation, AddFile, DelFile, ModifyFile, RenameMoveFile, AddDir, DelDir, RenameMoveDir, CloudFile
from .model import Tree, check_operation, basic_operation, File, LocalFile


def compare_file_by_cTag(before: CloudFile, after: CloudFile) -> bool:
    return before.cTag == after.cTag


def compare_file_by_mtime(last_sync_timestamp: int) -> Callable[[File, LocalFile], bool]:
    def _(before: File, after: LocalFile) -> bool:
        return after.st_mtime_ns <= last_sync_timestamp

    return _


def compare_file_by_hashes(id_to_path: Mapping[str, Path]) -> Callable[[LocalFile, CloudFile], bool]:
    def _(before: LocalFile, after: CloudFile) -> bool:
        if not _compare_size(before.size, after.size):
            return False
        hashes = after.hashes if after.hashes is not None else {}
        for algorithm in hashes:
            engine = HASH_ENGINES[algorithm]()
            engine.send(None)
            engine.send(id_to_path[before.id].read_bytes())
            if engine.send(None) != after.hashes[algorithm].upper():
                return False
        return True

    return _


def get_change_set(before: Tree, after: Tree, file_comparison: Callable[[File, File], bool]) -> Set[Operation]:
    change_set = set()

    for file_id in before.files.keys() | after.files.keys():
        if file_id not in before.files:
            file = after.files[file_id]
            change_set.add(AddFile(file.parent, file_id, file.name, file.size))
            continue
        if file_id not in after.files:
            change_set.add(DelFile(file_id))
            continue
        before_file = before.files[file_id]
        after_file = after.files[file_id]
        destination_id = None
        new_name = None
        if before_file.parent != after_file.parent:
            destination_id = after_file.parent
        if before_file.name != after_file.name:
            new_name = after_file.name
        if destination_id or new_name:
            change_set.add(RenameMoveFile(file_id, new_name, destination_id))

        if not file_comparison(before_file, after_file):
            change_set.add(ModifyFile(file_id, after_file.size))

    for dir_id in before.dirs.keys() | after.dirs.keys():
        if dir_id not in before.dirs:
            directory = after.dirs[dir_id]
            change_set.add(AddDir(directory.parent, dir_id, directory.name))
            continue
        if dir_id not in after.dirs:
            change_set.add(DelDir(dir_id))
            continue
        before_dir = before.dirs[dir_id]
        after_dir = after.dirs[dir_id]
        destination_id = None
        new_name = None
        if before_dir.parent != after_dir.parent:
            destination_id = after_dir.parent
        if before_dir.name != after_dir.name:
            new_name = after_dir.name
        if destination_id or new_name:
            change_set.add(RenameMoveDir(dir_id, new_name, destination_id))

    return change_set


def check_same_node_operations(cloud_changes: Set[Operation], local_changes: Set[Operation]) -> None:
    cloud_by_id = defaultdict(set)
    local_by_id = defaultdict(set)

    for operation in cloud_changes:
        if isinstance(operation, (AddFile, AddDir)):
            continue
        cloud_by_id[operation.id].add(operation)
    for operation in local_changes:
        if isinstance(operation, (AddFile, AddDir)):
            continue
        local_by_id[operation.id].add(operation)

    for identifier in cloud_by_id.keys() & local_by_id.keys():
        for cloud_change, local_change in itertools.product(cloud_by_id[identifier], local_by_id[identifier]):
            if isinstance(cloud_change, (
                    DelFile, ModifyFile, RenameMoveFile
            )) and isinstance(local_change, (
                    DelDir, RenameMoveDir
            )) or isinstance(cloud_change, (
                    DelDir, RenameMoveDir
            )) and isinstance(local_change, (
                    DelFile, ModifyFile, RenameMoveFile
            )):
                raise AssertionError('This should not happen, same id for different node type')
            if isinstance(cloud_change, (
                    DelFile, DelDir
            )) and isinstance(local_change, (
                    ModifyFile, RenameMoveFile, RenameMoveDir
            )) or isinstance(cloud_change, (
                    ModifyFile, RenameMoveFile, RenameMoveDir
            )) and isinstance(local_change, (
                    DelFile, DelDir
            )):
                raise Exception('Ambiguous operations of modifying deleted nodes')
            if isinstance(cloud_change, ModifyFile) and isinstance(local_change, ModifyFile):
                raise Exception('Modifying the same file twice')
            if isinstance(cloud_change, RenameMoveFile) and isinstance(local_change, RenameMoveFile):
                if cloud_change.name is not None and local_change.name is not None:
                    raise Exception('Ambiguous operations of renaming one file twice')
                if cloud_change.destination_id is not None and local_change.destination_id is not None:
                    raise Exception('Ambiguous operations of moving one file twice')
            if isinstance(cloud_change, RenameMoveDir) and isinstance(local_change, RenameMoveDir):
                if cloud_change.name is not None and local_change.name is not None:
                    raise Exception('Ambiguous operations of renaming one directory twice')
                if cloud_change.destination_id is not None and local_change.destination_id is not None:
                    raise Exception('Ambiguous operations of moving one directory twice')


# Logically this class is immutable, but frozen=True is inefficient for slots=True, so hash=True is necessary
@attr.s(slots=True, hash=True)
class Condition:
    pass


@attr.s(slots=True, hash=True)
class DirectoryExists(Condition):
    id = attr.ib(type=str)


@attr.s(slots=True, hash=True)
class NameReleased(Condition):
    parent_id = attr.ib(type=str)
    name = attr.ib(type=str)


@singledispatch
def effect_of_operation(args: Operation, tree: Tree) -> Optional[Condition]:
    raise NotImplementedError()


@effect_of_operation.register(AddFile)
def _(args: AddFile, tree: Tree) -> Optional[Condition]:
    return None


@effect_of_operation.register(DelFile)
def _(args: DelFile, tree: Tree) -> Optional[Condition]:
    return NameReleased(tree.files[args.id].parent, tree.files[args.id].name)


@effect_of_operation.register(ModifyFile)
def _(args: ModifyFile, tree: Tree) -> Optional[Condition]:
    return None


@effect_of_operation.register(RenameMoveFile)
def _(args: RenameMoveFile, tree: Tree) -> Optional[Condition]:
    file = tree.files[args.id]
    return NameReleased(file.parent, file.name)


@effect_of_operation.register(AddDir)
def _(args: AddDir, tree: Tree) -> Optional[Condition]:
    return DirectoryExists(args.child_id)


@effect_of_operation.register(DelDir)
def _(args: DelDir, tree: Tree) -> Optional[Condition]:
    directory = tree.dirs[args.id]
    return NameReleased(directory.parent, directory.name)


@effect_of_operation.register(RenameMoveDir)
def _(args: RenameMoveDir, tree: Tree) -> Optional[Condition]:
    directory = tree.dirs[args.id]
    return NameReleased(directory.parent, directory.name)


@singledispatch
def prerequisites_of_operation(args: Operation, tree: Tree) -> Set[Condition]:
    raise NotImplementedError()


@prerequisites_of_operation.register(AddFile)
def _(args: AddFile, tree: Tree) -> Set[Condition]:
    return {DirectoryExists(args.parent_id), NameReleased(args.parent_id, args.name)}


@prerequisites_of_operation.register(DelFile)
def _(args: DelFile, tree: Tree) -> Set[Condition]:
    return set()


@prerequisites_of_operation.register(ModifyFile)
def _(args: ModifyFile, tree: Tree) -> Set[Condition]:
    # The same question in the above function applies
    return set()


@prerequisites_of_operation.register(RenameMoveFile)
def _(args: RenameMoveFile, tree: Tree) -> Set[Condition]:
    file = tree.files[args.id]
    destination_id = args.destination_id if args.destination_id is not None else file.parent
    name = args.name if args.name is not None else file.name
    return {NameReleased(destination_id, name), DirectoryExists(destination_id)}


@prerequisites_of_operation.register(AddDir)
def _(args: AddDir, tree: Tree) -> Set[Condition]:
    return {DirectoryExists(args.parent_id), NameReleased(args.parent_id, args.name)}


@prerequisites_of_operation.register(DelDir)
def _(args: DelDir, tree: Tree) -> Set[Condition]:
    return {NameReleased(args.id, name) for name in tree.list_names(args.id)}


@prerequisites_of_operation.register(RenameMoveDir)
def _(args: RenameMoveDir, tree: Tree) -> Set[Condition]:
    directory = tree.dirs[args.id]
    destination_id = args.destination_id if args.destination_id is not None else directory.parent
    name = args.name if args.name is not None else directory.name
    return {NameReleased(destination_id, name), DirectoryExists(destination_id)}


def mark_dependencies(tree: Tree, change_set: Set[Operation]) -> Set[Tuple[Operation, Operation]]:
    dependencies = set()

    effects_to_operation = {}
    prerequisites_to_operation = defaultdict(set)
    for operation in change_set:
        effect = effect_of_operation(operation, tree)
        if effect is not None:
            effects_to_operation[effect] = operation
        for prerequisite in prerequisites_of_operation(operation, tree):
            prerequisites_to_operation[prerequisite].add(operation)

    for effect, producer in effects_to_operation.items():
        for consumer in prerequisites_to_operation[effect]:
            dependencies.add((consumer, producer))
        pass

    return dependencies


def topological_sort(change_set: Set[Operation], dependencies: Set[Tuple[Operation, Operation]]) -> Sequence[Operation]:
    result = []
    change_set = set(change_set)

    predecessors = defaultdict(set)
    successors = defaultdict(set)
    for consumer, producer in dependencies:
        predecessors[consumer].add(producer)
        successors[producer].add(consumer)

    while True:
        count = False
        for operation in set(change_set):
            if isinstance(operation, (AddFile, ModifyFile)):
                continue
            if not predecessors[operation]:
                count = True
                change_set.remove(operation)
                result.append(operation)
                for consumer in successors[operation]:
                    predecessors[consumer].remove(operation)
        if not count:
            break

    for operation in set(change_set):
        if isinstance(operation, (AddFile, ModifyFile)):
            change_set.remove(operation)
            result.append(operation)

    if change_set:
        raise Exception('Topological sorting failed, possible loops: ' + str(change_set))

    return result


def field_test(tree: Tree, script: Sequence[Operation]) -> Tree:
    field = copy.deepcopy(tree)
    for line in script:
        if check_operation(line, field):
            basic_operation(line, field)
        else:
            raise Exception('Failed in testing operation ' + repr(line))
        pass
    return field


def optimize_cloud_deletion(tree: Tree, script: Sequence[Operation]) -> Sequence[Operation]:
    result = []
    for line in script:
        if isinstance(line, (DelFile, DelDir)):
            if isinstance(line, DelFile):
                parent_id = tree.files[line.id].parent
            elif isinstance(line, DelDir):
                parent_id = tree.dirs[line.id].parent
            else:
                raise AssertionError()
            if any(isinstance(op, DelDir) and op.id == parent_id for op in script):
                continue
        result.append(line)
    return result


def _sha1():
    engine = hashlib.sha1()
    while True:
        chunk = yield
        if chunk is None:
            break
        engine.update(chunk)
    yield engine.hexdigest().upper()


def _crc32():
    engine = 0
    while True:
        chunk = yield
        if chunk is None:
            break
        engine = zlib.crc32(chunk, engine)
    yield (engine & 0xffffffff).to_bytes(4, 'little').hex().upper()


HASH_ENGINES = {
    'sha1Hash': _sha1,
    'crc32Hash': _crc32,
    # quickXOR hashes?
}
