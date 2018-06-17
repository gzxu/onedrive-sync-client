#!/usr/bin/env python3
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

import unittest

from onedrive.model import Tree, basic_operation, AddFile, File, Directory
from onedrive.algorithms import mark_dependencies, get_change_set, check_same_node_operations


class TestAlgorithm(unittest.TestCase):
    def setUp(self):
        self.tree = Tree('0')
        for file in [
            File('11', 'File 11', '0', 490),
            File('12', 'File 12', '0', 220),
            File('13', 'File 13', '0', 179),
            File('14', 'File 14', '1', 476),
            File('15', 'File 15', '1', 558),
            File('16', 'File 16', '1', 381),
            File('17', 'File 17', '2', 310),
            File('18', 'File 18', '2', 372),
            File('19', 'File 19', '2', 815),
            File('20', 'File 20', '3', 248),
            File('21', 'File 21', '3', 985),
            File('22', 'File 22', '4', 915),
            File('23', 'File 23', '5', 306),
            File('24', 'File 24', '5', 209),
            File('25', 'File 25', '6', 910)
        ]:
            self.tree.files[file.id] = file
        for directory in [
            Directory('1', 'Folder 1', '0'),
            Directory('2', 'Folder 2', '0'),
            Directory('3', 'Folder 3', '0'),
            Directory('4', 'Folder 4', '1'),
            Directory('5', 'Folder 5', '1'),
            Directory('6', 'Folder 6', '4'),
            Directory('7', 'Folder 7', '5')
        ]:
            self.tree.dirs[directory.id] = directory
        self.tree.reconstruct_by_parents()

    def tearDown(self):
        pass

    def test_change_set(self):
        self.assertTrue(get_change_set(self.tree, self.tree, lambda before, after: before.size == after.size) == set())

    def test_same_node(self):
        try:
            check_same_node_operations(set(), set())
        except Exception:
            self.assertTrue(False)


if __name__ == '__main__':
    unittest.main()
