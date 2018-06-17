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
from sqlite3 import Connection
from typing import NamedTuple, Any, Sequence, Tuple, Dict

Column = NamedTuple('Column', [('affinity', str), ('primary', bool)])


class EntityMeta(type):
    @classmethod
    def __prepare__(mcs, name: str, bases: Tuple, **kwargs):
        return OrderedDict()

    def __new__(mcs, name: str, bases: Tuple, namespace: Dict[str, Any], **kwargs):
        def __init__(self, *args):
            for arg, column in zip(args, columns):
                setattr(self, column, arg)

        columns = OrderedDict((key, value) for key, value in namespace.items() if isinstance(value, Column))
        if len(bases) and hasattr(bases[0], 'COLUMNS'):
            columns = OrderedDict(itertools.chain(bases[0].COLUMNS.items(), columns.items()))
        namespace['COLUMNS'] = columns
        namespace['__init__'] = __init__
        namespace['PRIMARY_FIELDS'] = tuple(name for name, column in columns.items() if column.primary)

        if 'TABLE_NAME' in namespace:
            table_name = namespace['TABLE_NAME']
        else:
            table_name = name
            namespace['TABLE_NAME'] = name

        sql_string = 'create table if not exists "' + table_name + '" ('
        sql_string += ','.join('"' + name + '" ' + column.affinity for name, column in columns.items())
        if namespace['PRIMARY_FIELDS']:
            sql_string += ', primary key ('
            sql_string += ','.join('"' + key + '"' for key in namespace['PRIMARY_FIELDS'])
            sql_string += ') on conflict replace'
        sql_string += ')'
        namespace['CREATE_SQL'] = sql_string

        return type.__new__(mcs, name, bases, dict(namespace))


class Entity(metaclass=EntityMeta):
    @staticmethod
    def connection(conn: Connection):
        def decorator(entity):
            if not issubclass(entity, Entity):
                raise ValueError()
            entity.CONNECTION = conn
            conn.execute(entity.CREATE_SQL)
            return entity

        return decorator

    pass


class DAO:
    @staticmethod
    def query(sql: str, scalar=False):
        def _decorator(func):
            def _decorated(self, *args, **kwargs):
                parameters = {key: value for key, value in zip(func.__code__.co_varnames[1:], args)}
                parameters.update(kwargs)
                cursor = self.ENTITY.CONNECTION.execute(sql.format(table_name=self.ENTITY.TABLE_NAME), parameters)
                if scalar:
                    row = cursor.fetchone()
                    return self.ENTITY(*row) if row is not None else None
                else:
                    return (self.ENTITY(*row) for row in cursor)

            return _decorated

        return _decorator

    @staticmethod
    def delete(func):
        if func.__code__.co_varnames != ('self', 'item'):
            raise AssertionError()

        def _decorated(self, item):
            sql_string = 'delete from "'
            sql_string += self.ENTITY.TABLE_NAME
            sql_string += '" where '
            sql_string += ' and '.join('"' + column + '" = :' + column for column in self.ENTITY.PRIMARY_FIELDS)
            parameters = {column: getattr(item, column) for column in self.ENTITY.PRIMARY_FIELDS}

            self.ENTITY.CONNECTION.execute(sql_string, parameters)

        return _decorated

    @staticmethod
    def insert(func):
        if func.__code__.co_varnames != ('self', 'items'):
            raise AssertionError()

        def _decorated(self, items: Sequence):
            sql_string = 'insert into "' + self.ENTITY.TABLE_NAME + '" values ('
            sql_string += ','.join(':' + column for column in self.ENTITY.COLUMNS)
            sql_string += ')'

            self.ENTITY.CONNECTION.executemany(sql_string, [
                {column: getattr(item, column) for column in self.ENTITY.COLUMNS} for item in items
            ])

        return _decorated

    @staticmethod
    def entity(entity_type):
        def decorator(dao):
            dao.ENTITY = entity_type
            return dao

        return decorator
