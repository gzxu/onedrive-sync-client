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

import argparse
import logging
from pathlib import Path
from requests.exceptions import HTTPError

from .sync import sync
from .database import get_config, set_config


def main():
    parser = argparse.ArgumentParser()
    parser.formatter_class = argparse.RawDescriptionHelpFormatter
    parser.add_argument('--set-location', metavar='DIRECTORY', help='Specify where to save your files')
    parser.add_argument('--set-root-id', metavar='ROOT_ID', help='''
    [DO NOT USE IF YOU DO NOT KNOW WHAT THIS MEANS] Specify the root id of your sub-folder in OneDrive
    ''')
    parser.description = '''Run this program with no arguments after setting location initiates a synchronization'''
    parser.epilog = '''
    Environment variables:
        ONEDRIVE_CONFIG_PATH: Path to the SQLite database storing configurations (Default: $XDG_DATA_DIR/onedrive.sqlite)
    '''

    args = parser.parse_args()

    logging.getLogger().setLevel(logging.INFO)

    if args.set_root_id is not None and args.set_location is None:
        parser.error('Cannot reset root id now')
    if args.set_location is not None:
        path = Path(args.set_location)
        if not path.is_dir():
            parser.error('The destination path should be a directory')
        if list(path.iterdir()):
            parser.error('The destination should be empty')
        set_config('local_path', args.set_location)
        logging.info('Destination path set successfully')
        if args.set_root_id is not None:
            set_config('root_id', args.set_root_id)
            logging.info('Root id set successfully')
        return 0

    if get_config('local_path') is None:
        parser.error('Use --set-location to set destination path first')

    try:
        return sync()
    except HTTPError as error:
        print(error.response.headers, error.response.content)
        raise
