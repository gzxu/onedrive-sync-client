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


def _compare_size(size1: int, size2: int):
    # Workaround for https://github.com/OneDrive/onedrive-api-docs/issues/123
    # All workarounds:
    #   * Here, together with every usage of this function
    #   * model.py, the size attributes for File instances are always 0
    #   * sdk.py, upload_large_file_by_parent() and download_file()

    # return size1 == size2
    return True
