"""Q-SL1 UART backup and same-unit stock-selector recovery. Python 3.11+."""
import argparse
import getpass
import json
from pathlib import Path
import warnings

from . import RecoveryError, captures
from .recovery import expected_image, restore_stock, two_passes
from .serial_link import HCI, drain_until_quiet, loopback, open_port, ports


def hidden(prompt):
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        return getpass.getpass(prompt)


def new_password():
    password = hidden('NEW backup passphrase (hidden, 12+ characters): ')
    if len(password) < 12 or password != hidden('Repeat backup passphrase (hidden): '):
        raise RecoveryError('Backup passphrase must match and contain at least 12 characters')
    return password


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='action', required=True)
    commands.add_parser('ports')
    for action in ('loopback', 'probe', 'backup'):
        command = commands.add_parser(action)
        command.add_argument('--port', required=True)
        command.add_argument('--adapter', choices=('c3', 'uart-3v3'), default='c3')
        if action == 'loopback':
            command.add_argument('--qsl1-disconnected', action='store_true', required=True)
        else:
            command.add_argument('--device-off-door', action='store_true', required=True)
        if action == 'backup':
            command.add_argument('--output-dir', type=Path, required=True)
    inspect = commands.add_parser('inspect')
    inspect.add_argument('--backup', type=Path, required=True)
    convert = commands.add_parser('import-dpapi')
    convert.add_argument('--input', type=Path, required=True)
    convert.add_argument('--output', type=Path, required=True)
    restore = commands.add_parser('restore-stock', help='Offline plan by default; execution is explicit')
    restore.add_argument('--original', type=Path, required=True, help='Same unit, known-working stock .qsb')
    restore.add_argument('--snapshot', type=Path, required=True, help='Recent full UART capture .qsb')
    restore.add_argument('--execute', action='store_true')
    restore.add_argument('--device-off-door', action='store_true')
    restore.add_argument('--port')
    restore.add_argument('--adapter', choices=('c3', 'uart-3v3'), default='c3')
    restore.add_argument('--output-dir', type=Path)
    return result


def run(args):
    if args.action == 'ports':
        print(json.dumps(ports()))
        return
    if args.action == 'inspect':
        data = captures.load(args.backup, hidden('Backup passphrase (hidden): '))
        from qsl1sec.image import validate_snapshot
        validate_snapshot(data, require_stock_selected=False)
        print(json.dumps({'full_capture_valid': True, 'stock_ds1_intact': True,
                          'ss1_marker': data[0], 'normal_boot_proved': False}))
        return
    if args.action == 'import-dpapi':
        from .legacy import read_legacy
        password = new_password()
        captures.save(args.output, read_legacy(args.input), password)
        print('Portable encrypted backup saved and verified; original DPAPI file retained.')
        return
    if args.action == 'restore-stock':
        if args.execute and not (args.device_off_door and args.port and args.output_dir):
            raise RecoveryError('Execution requires --device-off-door, --port and a NEW --output-dir')
        original = captures.load(args.original, hidden('ORIGINAL backup passphrase (hidden): '))
        snapshot = captures.load(args.snapshot, hidden('CURRENT snapshot passphrase (hidden): '))
        expected = expected_image(original, snapshot)
        if not args.execute:
            print(json.dumps({'offline_plan_only': True, 'hardware_opened': False,
                              'persistent_write_offset': 0, 'persistent_write_bytes': int(expected != snapshot),
                              'other_bytes_preserved': 65535, 'normal_boot_proved': False}))
            return
        password = new_password()
        directory = captures.new_directory(args.output_dir)
        with open_port(args.port, args.adapter) as connection:
            drain_until_quiet(connection)
            restore_stock(HCI(connection), original, snapshot, directory, password)
        print('Recovery transaction complete. Normal battery-only boot remains to be checked.')
        return
    password = new_password() if args.action == 'backup' else None
    directory = captures.new_directory(args.output_dir) if args.action == 'backup' else None
    with open_port(args.port, args.adapter) as connection:
        if args.action == 'loopback':
            print(json.dumps(loopback(connection)))
            return
        drain_until_quiet(connection)
        hci = HCI(connection)
        hci.require_version()
        if args.action == 'probe':
            print('Supported HCI version received. No RAM/EEPROM write sent.')
        else:
            two_passes(hci, directory, password, 'capture')
            print('Two independent encrypted captures saved and identical. No RAM/EEPROM write sent.')


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        run(args)
    except (KeyboardInterrupt, EOFError):
        print('Stopped. Preserve captures and receipt; never repeat a write without a fresh backup.')
        return 130
    except Exception as error:
        # Serial/path/crypto exceptions can contain private paths or device IDs.
        print('Stopped: ' + (str(error) if isinstance(error, RecoveryError) else type(error).__name__))
        print('Preserve captures and receipt. Check wiring, backup passphrases and prerequisites.')
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
