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

from .sync import sync, SyncDirection
from .database import CONFIG, clear_all_trees, session_scope


def main():
    parser = argparse.ArgumentParser()
    parser.formatter_class = argparse.RawDescriptionHelpFormatter

    group_operation = parser.add_mutually_exclusive_group()
    group_operation.add_argument('--download-only', action='store_true',
                                 help='Override the local tree with the cloud one')
    group_operation.add_argument('--upload-only', action='store_true',
                                 help='Override the cloud tree with the cloud one')

    group_config = parser.add_argument_group('Configurations')
    group_config.add_argument('--set-location', metavar='DIRECTORY', help='Specify where to save your files')
    group_config.add_argument('--set-root-id', metavar='ROOT_ID', help='''
    [DO NOT USE IF YOU DO NOT KNOW WHAT THIS MEANS] Specify the root id of your sub-folder in OneDrive
    ''')

    parser.description = '''Run this program with no arguments after setting location initiates a synchronization'''
    parser.epilog = '''
    Environment variables:
        ONEDRIVE_CONFIG_PATH: Path to the SQLite database storing configurations (Default: $XDG_DATA_DIR/onedrive.sqlite)
    '''

    args = parser.parse_args()

    logging.getLogger().setLevel(logging.INFO)

    if (args.download_only or args.upload_only) and (args.set_root_id is not None or args.set_location is not None):
        parser.error('Please configure before use')

    if args.set_root_id is not None and args.set_location is None:
        parser.error('Cannot reset root id now')
    if args.set_location is not None:
        path = Path(args.set_location)
        if not path.is_dir():
            parser.error('The destination path should be a directory')
        if list(path.iterdir()):
            parser.error('The destination should be empty')
        CONFIG.local_path = args.set_location
        logging.info('Destination path set successfully')
        if args.set_root_id is not None:
            CONFIG.root_id = args.set_root_id
            logging.info('Root id set successfully')
        else:
            del CONFIG.root_id
        with session_scope() as session:
            clear_all_trees(session)
            logging.info('Saved state reset successfully')
        return 0

    if getattr(CONFIG, 'local_path', None) is None:
        parser.error('Use --set-location to set destination path first')

    try:
        if args.download_only:
            return sync(SyncDirection.DOWNLOAD_ONLY)
        elif args.upload_only:
            return sync(SyncDirection.UPLOAD_ONLY)
        else:
            return sync(SyncDirection.TWO_WAY)
    except HTTPError as error:
        print(error.response.headers, error.response.content)
        raise
