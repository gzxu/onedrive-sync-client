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

import argparse
import json
import logging
from pathlib import Path

from .model import basic_operation
from .algorithms import get_change_set, check_same_node_operations, mark_dependencies, topological_sort, field_test
from .local import get_local_tree, local_apply_operation, convert_temp_id, register_real_id
from .sdk import get_session, retrieve_delta, cloud_apply_operation
from .database import get_config, set_config, load_saved_tree, save_tree


def sync() -> int:
    token = get_config('token', None)
    token = json.loads(token) if token is not None else None
    session = get_session(token, lambda new_token: set_config('token', json.dumps(new_token)))

    logging.info('Retrieving cloud tree structure')
    cloud_tree = retrieve_delta(session, get_config('root_id', None))
    logging.info('Cloud tree structure retrieved successfully')

    logging.info('Loading previous state from database')
    saved_tree = load_saved_tree()
    logging.info('Previous state loaded successfully')

    logging.info('Parsing local tree structure')
    local_tree, id_to_path = get_local_tree(get_config('local_path'), cloud_tree.root_id, cloud_tree)
    logging.info('Local tree structure parsed successfully')

    logging.info('Comparing trees and generating operations')

    cloud_changes = get_change_set(saved_tree, cloud_tree)
    local_changes = get_change_set(saved_tree, local_tree)

    check_same_node_operations(cloud_changes, local_changes)

    cloud_dependencies = mark_dependencies(saved_tree, cloud_changes)
    local_dependencies = mark_dependencies(saved_tree, local_changes)

    cloud_script = topological_sort(cloud_changes, cloud_dependencies)
    local_script = topological_sort(local_changes, local_dependencies)

    if field_test(saved_tree, cloud_script) != cloud_tree:
        raise AssertionError()
    if field_test(saved_tree, local_script) != local_tree:
        raise AssertionError()

    cloud_final = field_test(cloud_tree, local_script)
    local_final = field_test(local_tree, cloud_script)
    if cloud_final != local_final:
        raise AssertionError()

    logging.info('Compared successfully')
    if not cloud_script:
        logging.info('No operations need to be applied locally')
    else:
        logging.info('Applying these operations locally:')
        for line in cloud_script:
            logging.info(line.human_readable_string())
    if not local_script:
        logging.info('No operations need to be applied to the cloud')
    else:
        logging.info('Applying these operations to the cloud:')
        for line in local_script:
            logging.info(line.human_readable_string())

    if not cloud_script and not local_script:
        return 0

    while True:
        confirm = input('Proceed? [Y/n] ')
        confirm = confirm.lower()
        if confirm == '' or confirm == 'y':
            break
        if confirm == 'n':
            logging.info('Cancelled')
            return -1

    for index, line in enumerate(cloud_script):
        logging.info('Applying to local state (' + str(index + 1) + '/' + str(len(cloud_script)) + ')')
        local_apply_operation(line, local_tree, id_to_path, session)
        basic_operation(line, local_tree)
    real_id = {}
    for index, line in enumerate(local_script):
        logging.info('Applying to cloud state (' + str(index + 1) + '/' + str(len(local_script)) + ')')
        line = convert_temp_id(real_id, line)
        new_id = cloud_apply_operation(line, id_to_path, session)
        line = register_real_id(new_id, line, real_id)
        basic_operation(line, cloud_tree)

    save_tree(cloud_tree)
    return 0


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

    return sync()
