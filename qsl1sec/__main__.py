"""Explicit-target commands; importing or reading help never opens Bluetooth."""

import argparse
import asyncio
import base64
import getpass
import json
from pathlib import Path
import sys

from . import __version__
from .image import build, digest, DS1, DS_SIZE


def passphrase(new=False):
    value = getpass.getpass('Private backup passphrase (12+ characters; not sent anywhere): ')
    if len(value) < 12:
        raise ValueError('Passphrase must contain at least 12 characters')
    if new and value != getpass.getpass('Repeat passphrase: '):
        raise ValueError('Passphrases do not match')
    return value


def main():
    parser = argparse.ArgumentParser(description='Patch-only SEC002 toolkit for your own Q-SL1. Wireless installation is experimental.')
    parser.add_argument('--version', action='version', version=__version__)
    sub = parser.add_subparsers(dest='command', required=True)
    scan = sub.add_parser('scan', help='List Q-SL1 advertisements without writing')
    scan.add_argument('--seconds', type=int, default=10)
    scan.add_argument('--adapter', default='hci0')
    backup = sub.add_parser('backup', help='Read EEPROM twice and save an encrypted private backup; no writes')
    backup.add_argument('--address', required=True)
    backup.add_argument('--output', type=Path, required=True)
    backup.add_argument('--adapter', default='hci0')
    local = sub.add_parser('build', help='Generate the fixed SEC002 locally from your encrypted backup; no Bluetooth')
    local.add_argument('--backup', type=Path, required=True)
    local.add_argument('--output', type=Path, required=True)
    for name, help_text in [('stage', 'Write/check only inactive DS2; keep stock SS1 selected'),
                            ('activate', 'Commit selectors after rechecking DS1/DS2; disables future wireless updates'),
                            ('verify', 'Read model/version and probe raw-read denial; no writes or owner authentication')]:
        item = sub.add_parser(name, help=help_text)
        item.add_argument('--backup', type=Path, required=True)
        item.add_argument('--adapter', default='hci0')
    args = parser.parse_args()
    from . import private
    try:
        if args.command == 'build':
            password = passphrase()
            payload = private.load(args.backup, password)
            from .install import snapshot_data
            eeprom = snapshot_data(payload)
            candidate = build(eeprom[DS1:DS1 + DS_SIZE])
            private.save(args.output, {'kind': 'locally-patched-sec002', 'bytes': len(candidate),
                         'sha256': digest(candidate), 'ds_b64': base64.b64encode(candidate).decode()}, password)
            result = {'generated_privately': True, 'firmware': 'SEC002', 'sha256': digest(candidate), 'bytes': len(candidate)}
        else:
            from .radio import scan, address, linux_only
            linux_only()
            from . import install
            if args.command == 'scan':
                if not 1 <= args.seconds <= 60:
                    raise ValueError('Scan duration must be 1..60 seconds')
                result = asyncio.run(scan(args.seconds, args.adapter))
            elif args.command == 'backup':
                if args.output.exists():
                    raise FileExistsError('Backup already exists; choose a new filename')
                result = asyncio.run(install.backup(address(args.address), args.output, passphrase(new=True), args.adapter))
            else:
                password = passphrase()
                payload = private.load(args.backup, password)
                install.snapshot_data(payload)
                if args.command == 'verify':
                    result = asyncio.run(install.verify(payload['address'], payload['identity'], args.adapter))
                else:
                    result = asyncio.run(install.change(args.command, payload, args.backup, password, args.adapter))
        print(json.dumps(result, indent=2), flush=True)
        return 0
    except KeyboardInterrupt:
        print('Stopped. Do not blindly repeat a write; read the receipt and recovery instructions.', file=sys.stderr)
        return 130
    except Exception as error:
        # No response dumps, private key material or backup plaintext in errors.
        detail = str(error)[:180] if isinstance(error, (ValueError, RuntimeError, FileExistsError)) else type(error).__name__
        print(f'Stopped: {detail}', file=sys.stderr)
        return 1


if __name__ == '__main__':
    raise SystemExit(main())
