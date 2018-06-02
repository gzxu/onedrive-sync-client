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

import sqlite3
from typing import Sequence, Dict, Optional

from .model import Tree, File, Directory, basic_operation, DelDir
from .local import DATABASE_LOCATION

CONNECTION = sqlite3.connect(str(DATABASE_LOCATION))
CONNECTION.execute('create table if not exists config (key text primary key, value text)')
# Remember to add eTag information TODO
CONNECTION.execute('create table if not exists file_nodes (id text primary key, name text, checksum text, parent text)')
CONNECTION.execute('create table if not exists dir_nodes (id text primary key, name text, parent text)')
CONNECTION.execute('create table if not exists last_delta_files '
                   '(id text primary key, name text, checksum text, parent text)')
CONNECTION.execute('create table if not exists last_delta_dirs (id text primary key, name text, parent text)')


def set_config(key: str, value: str) -> None:
    with CONNECTION:
        CONNECTION.execute('insert or replace into config (key, value) values (:key, :value)', {
            'key': key,
            'value': value
        })


def get_config(key: str, default: str = None) -> Optional[str]:
    row = CONNECTION.execute('select value from config where key=:key', {
        'key': key
    }).fetchone()
    return row[0] if row is not None else default


def _save_tree(tree: Tree, root_id_key: str, files_table: str, dirs_table: str) -> None:
    with CONNECTION:
        CONNECTION.execute('insert or replace into config (key, value) values (:key, :value)', {
            'key': root_id_key,
            'value': tree.root_id
        })
        CONNECTION.execute('delete from ' + files_table)
        CONNECTION.execute('delete from ' + dirs_table)
        CONNECTION.executemany(
            'insert into ' + files_table + ' (id, name, checksum, parent) values (:id, :name, :checksum, :parent)', [{
                'id': node.id,
                'name': node.name,
                'checksum': node.checksum,
                'parent': node.parent
            } for node in tree.files.values()]
        )
        CONNECTION.executemany('insert into ' + dirs_table + ' (id, name, parent) values (:id, :name, :parent)', [{
            'id': node.id,
            'name': node.name,
            'parent': node.parent
        } for node in tree.dirs.values() if node.id != tree.root_id])


def _load_tree(root_id_key: str, files_table: str, dirs_table: str) -> Tree:
    tree = Tree(get_config(root_id_key))
    for row in CONNECTION.execute('select id, name, checksum, parent from ' + files_table):
        file = File(row[0], row[1], row[2])
        file.parent = row[3]
        tree.files[row[0]] = file
    for row in CONNECTION.execute('select id, name, parent from ' + dirs_table):
        directory = Directory(row[0], row[1])
        directory.parent = row[2]
        tree.dirs[row[0]] = directory
    tree.reconstruct_by_parents()
    return tree


def load_saved_tree() -> Tree:
    return _load_tree('root_id', 'file_nodes', 'dir_nodes')


def save_tree(tree: Tree) -> None:
    _save_tree(tree, 'root_id', 'file_nodes', 'dir_nodes')


def update_delta_tree(delta: Sequence[Dict], root_id: str) -> Tree:
    delta_link = get_config('delta_link', None)
    if delta_link is None:
        tree = Tree(root_id)
    else:
        tree = _load_tree('root_id', 'last_delta_files', 'last_delta_dirs')

    deleted = []
    for entry in delta:
        identifier = entry['id']
        if identifier == tree.root_id:
            continue
        if 'deleted' in entry:
            if identifier in tree.files:
                del tree.files[identifier]
            else:
                deleted.append(identifier)
        if 'file' in entry:
            if 'hashes' not in entry['file']:
                continue  # OneNote files have no hash. This is dangerous as normal files also have no hash on creation
            file = File(identifier, entry['name'], entry['file']['hashes']['sha1Hash'])
            file.parent = entry['parentReference']['id']
            tree.files[identifier] = file
        elif 'folder' in entry:
            directory = Directory(identifier, entry['name'])
            directory.parent = entry['parentReference']['id']
            tree.dirs[identifier] = directory

    tree.reconstruct_by_parents()

    while True:
        count = 0
        for identifier in list(deleted):
            current = tree.dirs[identifier]
            if not current.dirs and not current.files:
                deleted.remove(identifier)
                basic_operation(DelDir(identifier), tree)
                count += 1
        if count == 0:
            break

    _save_tree(tree, 'root_id', 'last_delta_files', 'last_delta_dirs')
    return tree
