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

from functools import singledispatch
from typing import Set, MutableMapping, Dict, Optional


class Node:
    def __init__(self, identifier: str, name: str):
        self._id = identifier
        self._name = name
        self._parent = None

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> str:
        return self._name

    @name.setter
    def name(self, value: str):
        self._name = value

    @property
    def parent(self) -> str:
        return self._parent

    @parent.setter
    def parent(self, value: str):
        self._parent = value

    def __eq__(self, other) -> bool:
        if not isinstance(other, Node):
            return False
        return self._id == other._id and self._name == other._name and self._parent == other._parent


class File(Node):
    def __init__(self, identifier: str, name: str, checksum: str):
        super().__init__(identifier, name)
        self._checksum = checksum

    @property
    def checksum(self) -> str:
        return self._checksum

    @checksum.setter
    def checksum(self, value: str):
        self._checksum = value

    def __eq__(self, other) -> bool:
        if not isinstance(other, File):
            return False
        if not super().__eq__(other):
            return False
        return self._checksum == other._checksum


class Directory(Node):
    def __init__(self, identifier: str, name: Optional[str]):
        super().__init__(identifier, name)
        self._files = set()
        self._dirs = set()

    @property
    def files(self) -> Set[str]:
        return self._files

    @property
    def dirs(self) -> Set[str]:
        return self._dirs

    def __eq__(self, other) -> bool:
        if not isinstance(other, Directory):
            return False
        if not super().__eq__(other):
            return False
        return self._files == other._files and self._dirs == other._dirs


class Tree:
    def __init__(self, root_id: str):
        # There is no complex references in this structure, so the
        # copy.deepcopy method can just be used
        self._root_id = root_id
        self._dirs = {root_id: Directory(root_id, None)}
        self._files = {}

    @property
    def root_id(self) -> str:
        return self._root_id

    @property
    def dirs(self) -> MutableMapping[str, Directory]:
        return self._dirs

    @property
    def files(self) -> MutableMapping[str, File]:
        return self._files

    def as_dict(self) -> Dict:
        def _as_dict(tree: Tree, subtree_id: str) -> Dict:
            return {
                'id': subtree_id,
                'name': tree.dirs[subtree_id].name,
                'children': [_as_dict(tree, child) for child in tree.dirs[subtree_id].dirs] + [{
                    'id': child,
                    'name': tree.files[child].name,
                    'checksum': tree.files[child].checksum
                } for child in tree.dirs[subtree_id].files]
            }

        return _as_dict(self, self._root_id)['children']

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

    def __eq__(self, other) -> bool:
        if not isinstance(other, Tree):
            return False
        if self.root_id != other._root_id:
            return False
        return self._files == other._files and self._dirs == other._dirs


class Operation:
    def human_readable_string(self) -> str:
        return ''


class AddFile(Operation):
    def __init__(self, parent_id: str, child_id: str, name: str, checksum: str):
        self._parent_id = parent_id
        self._child_id = child_id
        self._name = name
        self._checksum = checksum

    @property
    def parent_id(self) -> str:
        return self._parent_id

    @property
    def child_id(self) -> str:
        return self._child_id

    @property
    def name(self) -> str:
        return self._name

    @property
    def checksum(self) -> str:
        return self._checksum

    def __eq__(self, other) -> bool:
        return (isinstance(other, AddFile) and
                self._parent_id == other._parent_id and
                self._child_id == other._child_id and
                self._name == other._name and
                self._checksum == other._checksum)

    def __hash__(self) -> int:
        return hash((AddFile, self._parent_id, self._child_id, self._name, self._checksum))

    def human_readable_string(self) -> str:
        return 'Create file (' + self._checksum + ') ' + self._name + ' with id ' + self._child_id + ' to directory with id ' + self._parent_id


class DelFile(Operation):
    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    def __eq__(self, other) -> bool:
        return isinstance(other, DelFile) and self._id == other._id

    def __hash__(self) -> int:
        return hash((DelFile, self._id))

    def human_readable_string(self) -> str:
        return 'Remove file with id ' + self._id


class ModifyFile(Operation):
    def __init__(self, id: str, checksum: str):
        self._id = id
        self._checksum = checksum

    @property
    def id(self) -> str:
        return self._id

    @property
    def checksum(self) -> str:
        return self._checksum

    def __eq__(self, other) -> bool:
        return isinstance(other, ModifyFile) and self._id == other._id and self._checksum == other._checksum

    def __hash__(self) -> int:
        return hash((ModifyFile, self._id, self._checksum))

    def human_readable_string(self) -> str:
        return 'Override file with id ' + self._id + ' to (' + self._checksum + ')'


class RenameMoveFile(Operation):
    def __init__(self, id: str, name: Optional[str], destination_id: Optional[str]):
        self._id = id
        self._name = name
        self._destination_id = destination_id

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> Optional[str]:
        return self._name

    @property
    def destination_id(self) -> Optional[str]:
        return self._destination_id

    def __eq__(self, other) -> bool:
        return (isinstance(other, RenameMoveFile) and
                self._id == other._id and
                self._name == other._name and
                self._destination_id == other._destination_id)

    def __hash__(self) -> int:
        return hash((RenameMoveFile, self._id, self._name, self._destination_id))

    def human_readable_string(self) -> str:
        if self._name is None:
            return 'Move file ' + self._id + ' to directory with id ' + self._destination_id
        elif self._destination_id is None:
            return 'Rename file ' + self._id + ' to ' + self._name
        return 'Move file ' + self._id + ' to directory with id ' + self._destination_id + ' and rename to ' + self._name


class AddDir(Operation):
    def __init__(self, parent_id: str, child_id: str, name: str):
        self._parent_id = parent_id
        self._child_id = child_id
        self._name = name

    @property
    def parent_id(self) -> str:
        return self._parent_id

    @property
    def child_id(self) -> str:
        return self._child_id

    @property
    def name(self) -> str:
        return self._name

    def __eq__(self, other) -> bool:
        return (isinstance(other, AddDir) and
                self._parent_id == other._parent_id and
                self._child_id == other._child_id and
                self._name == other._name)

    def __hash__(self) -> int:
        return hash((AddDir, self._parent_id, self._child_id, self._name))

    def human_readable_string(self) -> str:
        return 'Create directory ' + self._name + ' with id ' + self._child_id + ' to directory with id ' + self._parent_id


class DelDir(Operation):
    def __init__(self, id: str):
        self._id = id

    @property
    def id(self) -> str:
        return self._id

    def __eq__(self, other) -> bool:
        return isinstance(other, DelDir) and self._id == other._id

    def __hash__(self) -> int:
        return hash((DelDir, self._id))

    def human_readable_string(self) -> str:
        return 'Remove directory with id ' + self._id


class RenameMoveDir(Operation):
    def __init__(self, id: str, name: Optional[str], destination_id: Optional[str]):
        self._id = id
        self._name = name
        self._destination_id = destination_id

    @property
    def id(self) -> str:
        return self._id

    @property
    def name(self) -> Optional[str]:
        return self._name

    @property
    def destination_id(self) -> Optional[str]:
        return self._destination_id

    def __eq__(self, other) -> bool:
        return (isinstance(other, RenameMoveDir) and
                self._id == other._id and
                self._name == other._name and
                self._destination_id == other._destination_id)

    def __hash__(self) -> int:
        return hash((RenameMoveDir, self._id, self._name, self._destination_id))

    def human_readable_string(self) -> str:
        if self._name is None:
            return 'Move directory ' + self._id + ' to directory with id ' + self._destination_id
        elif self._destination_id is None:
            return 'Rename directory ' + self._id + ' to ' + self._name
        return 'Move directory ' + self._id + ' to directory with id ' + self._destination_id + ' and rename to ' + self._name


@singledispatch
def basic_operation(args: Operation, tree: Tree) -> Node:
    raise NotImplementedError()


@basic_operation.register(AddFile)
def _(args: AddFile, tree: Tree) -> File:
    parent = tree.dirs[args.parent_id]
    child = File(args.child_id, args.name, args.checksum)
    child.parent = args.parent_id
    tree.files[args.child_id] = child
    parent.files.add(args.child_id)
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
    file.checksum = args.checksum
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
    parent = tree.dirs[args.parent_id]
    child = Directory(args.child_id, args.name)
    child.parent = args.parent_id
    tree.dirs[args.child_id] = child
    parent.dirs.add(args.child_id)
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
