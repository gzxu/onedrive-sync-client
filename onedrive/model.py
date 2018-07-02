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

from functools import singledispatch
from typing import Dict, Set

import attr

from . import _compare_size


@attr.s(slots=True)
class Node:
    id = attr.ib(type=str)
    name = attr.ib(type=str, default=None)
    parent = attr.ib(type=str, default=None)


@attr.s(slots=True)
class File(Node):
    # Workaround for https://github.com/OneDrive/onedrive-api-docs/issues/123
    size = attr.ib(type=int, default=0, converter=lambda _: 0)


@attr.s(slots=True)
class CloudFile(File):
    eTag = attr.ib(type=str, default=None)
    cTag = attr.ib(type=str, default=None)
    hashes = attr.ib(type=dict, factory=dict)


@attr.s(slots=True)
class LocalFile(File):
    st_mtime_ns = attr.ib(type=int, default=0)


@attr.s(slots=True)
class Directory(Node):
    files = attr.ib(type=Set[str], factory=set)
    dirs = attr.ib(type=Set[str], factory=set)


class Tree:
    def __init__(self, root_id: str):
        # There is no complex references in this structure, so the
        # copy.deepcopy method can just be used
        self._root_id = root_id
        self._dirs = {root_id: Directory(root_id)}
        self._files = {}

    @property
    def root_id(self) -> str:
        return self._root_id

    @property
    def dirs(self) -> Dict[str, Directory]:
        return self._dirs

    @property
    def files(self) -> Dict[str, File]:
        return self._files

    def reconstruct_by_parents(self) -> None:
        orphan_files = set()
        orphan_dirs = set()

        while True:
            count = False
            for key, value in self.files.items():
                if key in orphan_files:
                    continue
                if value.parent not in self.dirs or value.parent in orphan_dirs:
                    orphan_files.add(key)
                    count = True
            for key, value in self.dirs.items():
                if key in orphan_dirs or key == self.root_id:
                    continue
                if value.parent not in self.dirs or value.parent in orphan_dirs:
                    orphan_dirs.add(key)
                    count = True
            if not count:
                break

        for orphan in orphan_files:
            del self.files[orphan]
        for orphan in orphan_dirs:
            del self.dirs[orphan]

        for directory in self.dirs.values():
            directory.dirs.clear()
            directory.files.clear()
        for key, value in self.files.items():
            self.dirs[value.parent].files.add(key)
        for key, value in self.dirs.items():
            if key == self.root_id:
                continue
            self.dirs[value.parent].dirs.add(key)

    def list_names(self, dir_id: str) -> Set[str]:
        directory = self.dirs[dir_id]
        files = directory.files
        dirs = directory.dirs
        return {self.files[child].name for child in files} | {self.dirs[child].name for child in dirs}

    def equals(self, other) -> bool:
        if not isinstance(other, Tree):
            return False
        if self.root_id != other.root_id:
            return False

        if self.files.keys() != other.files.keys():
            return False
        for identifier in self.files.keys() & other.files.keys():
            if self.files[identifier].name != other.files[identifier].name:
                return False
            if self.files[identifier].parent != other.files[identifier].parent:
                return False
            if not _compare_size(self.files[identifier].size, other.files[identifier].size):
                return False

        if self.dirs.keys() != other.dirs.keys():
            return False
        for identifier in self.dirs.keys() & other.dirs.keys():
            if self.dirs[identifier].name != other.dirs[identifier].name:
                return False
            if self.dirs[identifier].parent != other.dirs[identifier].parent:
                return False

        return True


# Logically this class is immutable, but frozen=True is inefficient for slots=True, so hash=True is necessary
@attr.s(slots=True, hash=True)
class Operation:
    pass


@attr.s(slots=True, hash=True)
class AddFile(Operation):
    parent_id = attr.ib(type=str)
    child_id = attr.ib(type=str)
    name = attr.ib(type=str)
    size = attr.ib(type=int)

    def __str__(self) -> str:
        return 'Create file {name} with id {child_id} to directory with id {parent_id}'.format(
            name=self.name,
            child_id=self.child_id,
            parent_id=self.parent_id
        )


@attr.s(slots=True, hash=True)
class AddCloudFile(AddFile):
    eTag = attr.ib(type=str)
    cTag = attr.ib(type=str)


@attr.s(slots=True, hash=True)
class DelFile(Operation):
    id = attr.ib(type=str)

    def __str__(self) -> str:
        return 'Remove file with id {id}'.format(id=self.id)


@attr.s(slots=True, hash=True)
class ModifyFile(Operation):
    id = attr.ib(type=str)
    size = attr.ib(type=int)

    def __str__(self) -> str:
        return 'Override the content of the file with id {id}'.format(id=self.id)


@attr.s(slots=True, hash=True)
class ModifyCloudFile(ModifyFile):
    eTag = attr.ib(type=str)
    cTag = attr.ib(type=str)


@attr.s(slots=True, hash=True)
class RenameMoveFile(Operation):
    id = attr.ib(type=str)
    name = attr.ib(type=str)
    destination_id = attr.ib(type=str)

    def __str__(self) -> str:
        if self.name is None:
            return 'Move file {id} to directory with id {destination_id}'.format(
                id=self.id,
                destination_id=self.destination_id
            )
        elif self.destination_id is None:
            return 'Rename file {id} to {name}'.format(id=self.id, name=self.name)
        return 'Move file {id} to directory with id {destination_id} and rename it to {name}'.format(
            id=self.id,
            destination_id=self.destination_id,
            name=self.name
        )


@attr.s(slots=True, hash=True)
class AddDir(Operation):
    parent_id = attr.ib(type=str)
    child_id = attr.ib(type=str)
    name = attr.ib(type=str)

    def __str__(self) -> str:
        return 'Create directory {name} with id {child_id} to directory with id {parent_id}'.format(
            name=self.name,
            child_id=self.child_id,
            parent_id=self.parent_id
        )


@attr.s(slots=True, hash=True)
class DelDir(Operation):
    id = attr.ib(type=str)

    def __str__(self) -> str:
        return 'Remove directory with id {id}'.format(id=self.id)


@attr.s(slots=True, hash=True)
class RenameMoveDir(Operation):
    id = attr.ib(type=str)
    name = attr.ib(type=str)
    destination_id = attr.ib(type=str)

    def __str__(self) -> str:
        if self.name is None:
            return 'Move directory {id} to directory with id {destination_id}'.format(
                id=self.id,
                destination_id=self.destination_id
            )
        elif self.destination_id is None:
            return 'Rename directory {id} to {name}'.format(id=self.id, name=self.name)
        return 'Move directory {id} to directory with id {destination_id} and rename it to {name}'.format(
            id=self.id,
            destination_id=self.destination_id,
            name=self.name
        )


@singledispatch
def basic_operation(args: Operation, tree: Tree) -> Node:
    raise NotImplementedError()


@basic_operation.register(AddFile)
def _(args: AddFile, tree: Tree) -> File:
    if isinstance(args, AddCloudFile):
        child = CloudFile(args.child_id, args.name, args.parent_id, args.size, args.eTag, args.cTag, {})
    else:
        child = File(args.child_id, args.name, args.parent_id, args.size)
    tree.files[args.child_id] = child
    tree.dirs[args.parent_id].files.add(args.child_id)
    return child


@basic_operation.register(DelFile)
def _(args: DelFile, tree: Tree) -> File:
    child = tree.files[args.id]
    parent = tree.dirs[child.parent]
    parent.files.remove(args.id)
    del tree.files[args.id]
    return child


@basic_operation.register(ModifyFile)
def _(args: ModifyFile, tree: Tree) -> File:
    file = tree.files[args.id]
    file.size = args.size
    if isinstance(args, ModifyCloudFile) and isinstance(file, CloudFile):
        file.eTag = args.eTag
        file.cTag = args.cTag
    return file


@basic_operation.register(RenameMoveFile)
def _(args: RenameMoveFile, tree: Tree) -> File:
    child = tree.files[args.id]
    if args.name is not None:
        child.name = args.name
    if args.destination_id is not None:
        source = tree.dirs[child.parent]
        destination = tree.dirs[args.destination_id]
        child.parent = args.destination_id
        source.files.remove(args.id)
        destination.files.add(args.id)
    return child


@basic_operation.register(AddDir)
def _(args: AddDir, tree: Tree) -> Directory:
    child = Directory(args.child_id, args.name, args.parent_id)
    tree.dirs[args.child_id] = child
    tree.dirs[args.parent_id].dirs.add(args.child_id)
    return child


@basic_operation.register(DelDir)
def _(args: DelDir, tree: Tree) -> Directory:
    child = tree.dirs[args.id]
    parent = tree.dirs[child.parent]
    parent.dirs.remove(args.id)

    def _del_dir(identifier: str) -> None:
        # Remove the directory from the index of the tree, recursively
        current = tree.dirs[identifier]
        for directory_id in current.dirs:
            _del_dir(directory_id)
        for file_id in current.files:
            # We do not need to remove the file from the containing directory
            # as we want to preserve the structure of this subtree
            del tree.files[file_id]
        del tree.dirs[identifier]

    _del_dir(args.id)
    return child


@basic_operation.register(RenameMoveDir)
def _(args: RenameMoveDir, tree: Tree) -> Directory:
    child = tree.dirs[args.id]
    if args.name is not None:
        child.name = args.name
    if args.destination_id is not None:
        source = tree.dirs[child.parent]
        destination = tree.dirs[args.destination_id]
        child.parent = args.destination_id
        source.dirs.remove(args.id)
        destination.dirs.add(args.id)
    return child


@singledispatch
def check_operation(args: Operation, tree: Tree) -> bool:
    raise NotImplementedError()


@check_operation.register(AddFile)
def _(args: AddFile, tree: Tree) -> bool:
    if args.parent_id not in tree.dirs:
        return False
    if args.name in tree.list_names(args.parent_id):
        return False
    return True


@check_operation.register(DelFile)
def _(args: DelFile, tree: Tree) -> bool:
    if args.id not in tree.files:
        return False
    return True


@check_operation.register(ModifyFile)
def _(args: ModifyFile, tree: Tree) -> bool:
    if args.id not in tree.files:
        return False
    return True


@check_operation.register(RenameMoveFile)
def _(args: RenameMoveFile, tree: Tree) -> bool:
    if args.id not in tree.files:
        return False
    if args.destination_id is not None:
        if args.destination_id not in tree.dirs:
            return False
        if args.name is not None:
            if args.name in tree.list_names(args.destination_id):
                return False
        else:
            if tree.files[args.id].name in tree.list_names(args.destination_id):
                return False
    else:
        if args.name is not None:
            if args.name in tree.list_names(tree.files[args.id].parent):
                return False
    return True


@check_operation.register(AddDir)
def _(args: AddDir, tree: Tree) -> bool:
    if args.parent_id not in tree.dirs:
        return False
    if args.name in tree.list_names(args.parent_id):
        return False
    return True


@check_operation.register(DelDir)
def _(args: DelDir, tree: Tree) -> bool:
    if args.id not in tree.dirs:
        return False
    directory = tree.dirs[args.id]
    if directory.files or directory.dirs:
        return False
    return True


@check_operation.register(RenameMoveDir)
def _(args: RenameMoveDir, tree: Tree) -> bool:
    if args.id not in tree.dirs:
        return False
    if args.destination_id is not None:
        if args.destination_id not in tree.dirs:
            return False
        if args.name is not None:
            if args.name in tree.list_names(args.destination_id):
                return False
        else:
            if tree.dirs[args.id].name in tree.list_names(args.destination_id):
                return False
    else:
        if args.name is not None:
            if args.name in tree.list_names(tree.dirs[args.id].parent):
                return False
    return True
