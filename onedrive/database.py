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
from collections import OrderedDict
from contextlib import contextmanager
from enum import IntEnum

from sqlalchemy import create_engine, Column, String, Integer
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker

from .platform import DATABASE_LOCATION
from .model import Tree, Directory, CloudFile

ENGINE = create_engine('sqlite:///' + str(DATABASE_LOCATION))
Session = sessionmaker(bind=ENGINE)


@contextmanager
def session_scope():
    """Provide a transactional scope around a series of operations."""
    session = Session()
    try:
        yield session
        session.commit()
    except SQLAlchemyError:
        session.rollback()
        raise
    finally:
        session.close()


class TreeType(IntEnum):
    SAVED = 1
    DELTA = 2


Base = declarative_base()


class ConfigEntity(Base):
    __tablename__ = 'config'
    key = Column(String, primary_key=True)
    value = Column(String)


class FileEntity(Base):
    __tablename__ = 'file_nodes'
    tree = Column(Integer, primary_key=True)
    id = Column(String, primary_key=True)
    name = Column(String)
    size = Column(Integer)
    eTag = Column(String)
    cTag = Column(String)
    parent = Column(String)


class DirEntity(Base):
    __tablename__ = 'dir_nodes'
    tree = Column(Integer, primary_key=True)
    id = Column(String, primary_key=True)
    name = Column(String)
    parent = Column(String)


class HashEntity(Base):
    __tablename__ = 'hashes'
    id = Column(String, primary_key=True)
    type = Column(String, primary_key=True)
    value = Column(String)


Base.metadata.create_all(ENGINE)


class Config:
    def __getattr__(self, item: str) -> str:
        with session_scope() as session:
            result = session.query(ConfigEntity).get(item)
            if result is None:
                raise IndexError()
            else:
                return result.value

    def __setattr__(self, key: str, value: str) -> None:
        with session_scope() as session:
            session.merge(ConfigEntity(key=key, value=value))

    def __delattr__(self, item: str) -> None:
        with session_scope() as session:
            session.query(ConfigEntity).filter_by(key=item).delete()


CONFIG = Config()
# if int(getattr(CONFIG, 'db_version', 0)) < 1:
#     logging.warning('The database is outdated, please remove ' + str(DATABASE_LOCATION) + ' and rerun this program')
#     sys.exit(-1)
CONFIG.db_version = 1


def save_tree(session: Session.class_, tree: Tree, tree_type: TreeType):
    files = tree.files.values()
    dirs = tree.dirs.values()

    session.query(FileEntity).filter_by(tree=tree_type.value).delete()
    session.add_all(FileEntity(
        tree=tree_type,
        id=file.id,
        name=file.name,
        size=file.size,
        eTag=file.eTag,
        cTag=file.cTag,
        parent=file.parent
    ) for file in files)
    if tree_type == TreeType.DELTA:  # Hashes is not required to be saved for next comparison
        session.query(HashEntity).delete()
        session.add_all(itertools.chain.from_iterable((HashEntity(
            id=file.id,
            type=type_,
            value=value
        ) for type_, value in file.hashes.items()) for file in files))
    session.query(DirEntity).filter_by(tree=tree_type.value).delete()
    session.add_all(DirEntity(
        tree=tree_type,
        id=directory.id,
        name=directory.name,
        parent=directory.parent
    ) for directory in dirs)


def load_tree(session: Session.class_, tree_type: TreeType) -> Tree:
    files = OrderedDict()
    dirs = OrderedDict()
    for entity in session.query(FileEntity).filter_by(tree=tree_type.value):
        if tree_type == TreeType.DELTA:
            hashes = session.query(HashEntity).filter_by(id=entity.id).all()
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
    for entity in session.query(DirEntity).filter_by(tree=tree_type.value):
        dirs[entity.id] = Directory(entity.id, entity.name, entity.parent)

    tree = Tree(CONFIG.root_id)
    tree.files.update(files)
    tree.dirs.update(dirs)
    tree.reconstruct_by_parents()

    return tree


def clear_all_trees(session: Session.class_):
    session.query(FileEntity).delete()
    session.query(DirEntity).delete()
    session.query(HashEntity).delete()
