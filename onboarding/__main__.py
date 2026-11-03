"""Owner-card enrollment, encrypted recovery and minimal HomeKit key export."""
import argparse
import asyncio
import getpass
from pathlib import Path
import sys
import warnings

from .mq import LIBRARY_SHA256, load_coefficients
from .vault import export_owner, read_vault, vault_lock
from . import EnrollmentError, PrerequisiteError


def hidden(prompt):
    # Refuse getpass's visible-input fallback; never accept secrets in arguments.
    with warnings.catch_warnings():
        warnings.simplefilter('error', getpass.GetPassWarning)
        return getpass.getpass(prompt)


def parser():
    result = argparse.ArgumentParser(description=__doc__)
    commands = result.add_subparsers(dest='action', required=True)
    inspect_apk = commands.add_parser('inspect-apk', help='Validate your local APK without extracting files')
    inspect_apk.add_argument('--apk', required=True, type=Path)
    for action in ('enroll', 'inspect', 'verify', 'export'):
        command = commands.add_parser(action)
        command.add_argument('--vault', required=True, type=Path)
        if action in ('enroll', 'verify'):
            command.add_argument('--relay-config', type=Path, help='Optional private ESPHome relay config')
        if action == 'enroll':
            command.add_argument('--apk', required=True, type=Path)
            command.add_argument('--resume', action='store_true', help='Reuse the same saved keys after a partial enrollment')
            command.add_argument('--device-off-door', required=True, action='store_true',
                                 help='Confirm the owned lock is removed from the door for enrollment')
        if action == 'export':
            command.add_argument('--output', required=True, type=Path, help='New private owner.json; never overwritten')
    return result


async def run(args):
    if args.action == 'inspect-apk':
        load_coefficients(args.apk)
        print('Supported MQ library: ' + LIBRARY_SHA256 + '; no vendor data exported.')
        return
    with vault_lock(args.vault):
        if args.action == 'enroll':
            from .enrollment import decode_card_code, enroll_saved, normalize_serial
            from .runtime import discover
            if not args.resume and args.vault.exists():
                raise PrerequisiteError('Vault already exists; use verify or explicit --resume')
            coefficients = load_coefficients(args.apk)
            serial = normalize_serial(hidden('Owner-card serial (hidden): '))
            card_key = decode_card_code(hidden('Owner-card security code (hidden): '))
            password = hidden('Recovery-vault passphrase (hidden): ')
            if not args.resume:
                if len(password) < 12 or password != hidden('Repeat NEW passphrase (hidden): '):
                    raise PrerequisiteError('New passphrase must match and contain at least 12 characters')
            else:
                # Fail before any Bluetooth work if this is the wrong vault password.
                read_vault(args.vault, password)
            advertisement = await discover(serial, args.relay_config)
            await enroll_saved(advertisement, serial, card_key, coefficients, args.vault, password,
                               args.resume, args.relay_config)
            print('Authenticated status verified. Use export to create a private operation key.')
        else:
            password = hidden('Recovery-vault passphrase (hidden): ')
            if args.action == 'verify':
                from .enrollment import verify_saved
                await verify_saved(args.vault, password, args.relay_config)
                print('Authenticated read-only status succeeded; vault marked verified.')
            else:
                record = read_vault(args.vault, password)
                if args.action == 'inspect':
                    # Never print optional free text from an imported vault.
                    print('Vault valid. State: ' + record['state'] + '. No key material displayed.')
                else:
                    export_owner(record, args.output)
                    print('Private operation key exported. Keep it out of Git, chat and shared folders.')


def main(argv=None):
    args = parser().parse_args(argv)
    try:
        asyncio.run(run(args))
    except (KeyboardInterrupt, EOFError):
        print('Stopped. Keep any existing encrypted recovery vault; no automatic retry.', file=sys.stderr)
        return 130
    except Exception as error:
        # Third-party BLE/JSON/path exceptions can contain device IDs or secrets.
        # Own fixed messages are useful, but do not echo untrusted exception strings.
        if isinstance(error, (EnrollmentError, PrerequisiteError)):
            print('Stopped: ' + str(error), file=sys.stderr)
        elif isinstance(error, FileExistsError):
            print('Stopped: refusing to overwrite an existing private file.', file=sys.stderr)
        else:
            print('Stopped: ' + type(error).__name__ + '. Check prerequisites, passphrase and private files.', file=sys.stderr)
        print('Keep the encrypted vault and backups. After a timeout, try verify before --resume.', file=sys.stderr)
        return 1
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
