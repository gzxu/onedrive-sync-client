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

# According to https://docs.microsoft.com/en-us/onedrive/developer/code-snippets/quickxorhash
# But these functions have different results from https://github.com/skilion/onedrive/blob/v1.1.1/src/qxor.d#L81
# Don't know why

from typing import BinaryIO


def XorHash(stream: BinaryIO) -> bytearray:
    result = bytearray(20)
    count = 0
    while True:
        byte = stream.read(1)
        if byte is None:
            raise NotImplementedError('Asynchronous operation not supported')
        elif not len(byte):
            count += 1
            break
        byte = byte[0]

        location = count * 11 % (20 * 8)
        higher = byte >> (8 - location % 8)
        lower = (byte << (location % 8)) & 0xff
        result[location // 8] ^= lower
        result[(location // 8 + 1) % 20] ^= higher

        count += 1
    result.reverse()
    result[:8] = (count ^ int.from_bytes(result[:8], 'little')).to_bytes(8, 'little')
    return result


def XorHash(stream: BinaryIO) -> bytearray:
    result = 0
    count = 0
    while True:
        byte = stream.read(1)
        if byte is None:
            raise NotImplementedError('Asynchronous operation not supported')
        elif not len(byte):
            count += 1
            break
        byte = byte[0]
        byte <<= ((count * 11) % (20 * 8))
        byte = (byte % (1 << (20 * 8))) | (byte // (1 << (20 * 8)))
        result ^= byte

        count += 1
    result = bytearray(reversed(result.to_bytes(20, 'little')))
    result[:8] = (count ^ int.from_bytes(result[:8], 'little')).to_bytes(8, 'little')
    return result
