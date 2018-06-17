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
import itertools
import sqlite3
from collections import OrderedDict
from enum import IntEnum
from typing import Iterable

from .model import CloudFile
from .dao import Entity, Column, DAO
from .model import Tree, Directory
from .platform import DATABASE_LOCATION


class TreeType(IntEnum):
    SAVED = 1
    DELTA = 2


CONNECTION = sqlite3.connect(str(DATABASE_LOCATION))


@Entity.connection(CONNECTION)
class ConfigEntity(Entity):
    TABLE_NAME = 'config'
    key = Column('text', True)
    value = Column('text', False)


@Entity.connection(CONNECTION)
class FileEntity(Entity):
    TABLE_NAME = 'file_nodes'
    tree = Column('integer', True)
    id = Column('text', True)
    name = Column('text', False)
    size = Column('integer', False)
    eTag = Column('text', False)
    cTag = Column('text', False)
    parent = Column('text', False)


@Entity.connection(CONNECTION)
class DirEntity(Entity):
    TABLE_NAME = 'dir_nodes'
    tree = Column('integer', True)
    id = Column('text', True)
    name = Column('text', False)
    parent = Column('text', False)


@Entity.connection(CONNECTION)
class HashEntity(Entity):
    TABLE_NAME = 'hashes'
    id = Column('text', True)
    type = Column('text', True)
    value = Column('text', False)


@DAO.entity(ConfigEntity)
class ConfigDAO(DAO):
    @DAO.query('select * from "{table_name}" where "key" = :key', scalar=True)
    def get_value(self, key: str): pass

    @DAO.insert
    def populate(self, items): pass

    @DAO.delete
    def del_value(self, item): pass


@DAO.entity(FileEntity)
class FilesDAO(DAO):
    @DAO.query('select * from "{table_name}" where "tree" = :tree')
    def get_all_from_tree(self, tree: TreeType) -> Iterable[FileEntity]: pass

    @DAO.insert
    def populate(self, items): pass

    @DAO.query('delete from "{table_name}" where "tree" = :tree', scalar=True)
    def clear_tree(self, tree: TreeType): pass

    @DAO.query('delete from "{table_name}"', scalar=True)
    def clear(self): pass


@DAO.entity(DirEntity)
class DirsDAO(DAO):
    @DAO.query('select * from "{table_name}" where "tree" = :tree')
    def get_all_from_tree(self, tree: TreeType) -> Iterable[DirEntity]: pass

    @DAO.insert
    def populate(self, items): pass

    @DAO.query('delete from "{table_name}" where "tree" = :tree', scalar=True)
    def clear_tree(self, tree: TreeType): pass

    @DAO.query('delete from "{table_name}"', scalar=True)
    def clear(self): pass


@DAO.entity(HashEntity)
class HashDAO(DAO):
    @DAO.query('select * from "{table_name}" where "id" = :id')
    def get_hashes_by_id(self, id: str) -> Iterable[HashEntity]: pass

    @DAO.insert
    def populate(self, items): pass

    @DAO.query('delete from "{table_name}"', scalar=True)
    def clear(self): pass


class Config:
    def __init__(self):
        self._dao = ConfigDAO()

    def __getitem__(self, item: str) -> str:
        entity = self._dao.get_value(item)
        if entity is None:
            raise IndexError()
        else:
            return entity.value

    def __setitem__(self, key: str, value: str) -> None:
        self._dao.populate((ConfigEntity(key, value),))

    def __delitem__(self, item: str) -> None:
        self._dao.del_value(ConfigEntity(item, None))

    def __getattr__(self, item: str) -> str:
        try:
            return self.__getitem__(item)
        except IndexError:
            raise AttributeError()

    def __setattr__(self, key: str, value: str) -> None:
        if key == '_dao':
            object.__setattr__(self, key, value)
            return
        with self._dao.ENTITY.CONNECTION:
            self.__setitem__(key, value)

    def __delattr__(self, item: str) -> None:
        with self._dao.ENTITY.CONNECTION:
            self.__delitem__(item)


CONFIG = Config()
# if int(getattr(CONFIG, 'db_version', 0)) < 1:
#     logging.warning('The database is outdated, please remove ' + str(DATABASE_LOCATION) + ' and rerun this program')
#     sys.exit(-1)
CONFIG.db_version = 1


class TreeAdapter:
    def __init__(self):
        self._files_dao = FilesDAO()
        self._hash_dao = HashDAO()
        self._dirs_dao = DirsDAO()

    def save_tree(self, tree: Tree, tree_type: TreeType):
        files = tree.files.values()
        dirs = tree.dirs.values()

        self._files_dao.clear_tree(tree_type)
        self._files_dao.populate(FileEntity(
            tree_type,
            file.id,
            file.name,
            file.size,
            file.eTag,
            file.cTag,
            file.parent
        ) for file in files)
        if tree_type == TreeType.DELTA:  # Hashes is not required to be saved for next comparison
            self._hash_dao.clear()
            self._hash_dao.populate(itertools.chain.from_iterable((HashEntity(
                file.id,
                type_,
                value
            ) for type_, value in file.hashes.items()) for file in files))
        self._dirs_dao.clear_tree(tree_type)
        self._dirs_dao.populate(DirEntity(
            tree_type,
            directory.id,
            directory.name,
            directory.parent
        ) for directory in dirs)

    def load_tree(self, tree_type: TreeType) -> Tree:
        files = OrderedDict()
        dirs = OrderedDict()
        for entity in self._files_dao.get_all_from_tree(tree_type):
            if tree_type == TreeType.DELTA:
                hashes = self._hash_dao.get_hashes_by_id(entity.id)
            else:
                hashes = []
            files[entity.id] = CloudFile(
                entity.id,
                entity.name,
                entity.parent,
                entity.size,
                entity.eTag,
                entity.cTag,
                {hash_entity.type: hash_entity.value for hash_entity in hashes}
            )
        for entity in self._dirs_dao.get_all_from_tree(tree_type):
            dirs[entity.id] = Directory(entity.id, entity.name, entity.parent)

        tree = Tree(CONFIG.root_id)
        tree.files.update(files)
        tree.dirs.update(dirs)
        tree.reconstruct_by_parents()

        return tree

    def clear_all(self):
        self._files_dao.clear()
        self._dirs_dao.clear()
        self._hash_dao.clear()


TREE_ADAPTER = TreeAdapter()
