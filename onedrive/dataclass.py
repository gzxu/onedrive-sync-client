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
import copy
from collections import OrderedDict
from typing import NamedTuple, Any, Tuple, Dict

Field = NamedTuple('Field', [('type', Any), ('readonly', bool), ('defaults', Any)])


def _init(self, *args, **kwargs):
    for name, field in self.FIELDS.items():
        setattr(self, '_' + name, copy.copy(field.defaults))  # In case the default value is a container
    for arg, (name, field) in zip(args, self.FIELDS.items()):
        setattr(self, '_' + name, arg)
    for name, value in kwargs.items():
        if name in self.FIELDS:
            setattr(self, '_' + name, value)


def _deepcopy():
    pass


def _eq(self, other) -> bool:
    return all(getattr(self, '_' + field) == getattr(other, '_' + field) for field in self.FIELDS)


def _hash(self) -> int:
    return hash((type(self),) + tuple(getattr(self, '_' + field) for field in self.FIELDS))


def _fget(name: str, field: Field):
    def fget(self):
        if name == 'size':
            return 0  # Workaround for https://github.com/OneDrive/onedrive-api-docs/issues/123
        return getattr(self, '_' + name)

    fget.__annotations__ = {'return': field.type}
    return fget


def _fset(name: str, field: Field):
    def fset(self, value):
        setattr(self, '_' + name, value)

    fset.__annotations__ = {'value': field.type}
    return fset


class DataClassMeta(type):
    @classmethod
    def __prepare__(mcs, name: str, bases: Tuple, **kwargs):
        return OrderedDict()

    def __new__(mcs, name: str, bases: Tuple, namespace: Dict[str, Any], **kwargs):
        fields = OrderedDict((key, value) for key, value in namespace.items() if isinstance(value, Field))
        if len(bases) and hasattr(bases[0], 'FIELDS'):
            fields = OrderedDict(itertools.chain(bases[0].FIELDS.items(), fields.items()))
        namespace['FIELDS'] = fields
        namespace['__init__'] = _init
        if all(field.readonly for field in fields.values()):
            namespace['__eq__'] = _eq
            namespace['__hash__'] = _hash
        for name, field in fields.items():
            namespace[name] = property(_fget(name, field), _fset(name, field) if not field.readonly else None)
        return type.__new__(mcs, name, bases, dict(namespace))


class DataClass(metaclass=DataClassMeta):
    pass
