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

import os
import errno
import sys
from pathlib import Path
from typing import Optional

if sys.platform == 'linux':
    if 'ONEDRIVE_CONFIG_PATH' in os.environ:
        DATABASE_LOCATION = Path(os.environ['ONEDRIVE_CONFIG_PATH'])
    else:
        Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')).mkdir(parents=True, exist_ok=True)
        DATABASE_LOCATION = Path(os.environ.get('XDG_DATA_HOME', Path.home() / '.local' / 'share')) / 'onedrive.sqlite'
    XATTR_ONEDRIVE_ID = 'user.onedrive.id'


    def save_id_in_metadata(identifier: str, path):
        path = Path(path)
        os.setxattr(str(path), XATTR_ONEDRIVE_ID, identifier.encode())


    def load_id_from_metadata(path) -> Optional[str]:
        path = Path(path)
        try:
            return os.getxattr(str(path), XATTR_ONEDRIVE_ID).decode()
        except OSError as error:
            if error.errno != errno.ENODATA:
                raise
            else:
                return None
else:
    DATABASE_LOCATION = Path(os.environ.get('LOCALAPPDATA', Path.home() / 'AppData' / 'Local')) / 'onedrive.sqlite'
    raise Exception('Operating system currently unsupported ' + sys.platform)
