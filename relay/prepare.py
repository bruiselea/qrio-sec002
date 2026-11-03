"""Prepare a private ESPHome build folder. Does not flash or contact a lock."""

import argparse
import base64
import getpass
import json
import os
from pathlib import Path
import secrets


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--demo', action='store_true', help='Use synthetic Wi-Fi for compile checks only')
    parser.add_argument('--ssid-file', type=Path, help='Private file containing a locally supplied SSID')
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        raise FileExistsError('Use a new private build directory; existing credentials are never overwritten')
    if args.demo:
        ssid, password = 'QRIO_BUILD_TEST', 'not-a-real-wifi-password'
    else:
        ssid = (json.loads(args.ssid_file.read_text(encoding='utf-8'))['ssid'] if args.ssid_file
                else input('2.4GHz Wi-Fi SSID (local terminal only): ').strip())
        password = getpass.getpass('Wi-Fi password (hidden): ')
        if not ssid or not 8 <= len(password) <= 63:
            raise ValueError('Use a named WPA2/WPA3 network and an 8..63 character password')
    output.mkdir(parents=True, mode=0o700)
    values = {'wifi_ssid': ssid, 'wifi_password': password,
              'api_encryption_key': base64.b64encode(secrets.token_bytes(32)).decode()}
    files = {'secrets.yaml': '\n'.join(k+': '+json.dumps(v, ensure_ascii=False) for k,v in values.items())+'\n',
             'xiao-esp32c3.yaml': Path(__file__).with_name('xiao-esp32c3.yaml').read_text(encoding='utf-8'),
             '.gitignore': '*\n'}
    for name, text in files.items():
        fd = os.open(output/name, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd,'w',encoding='utf-8',newline='\n') as stream:
            stream.write(text)
    print('Prepared private build directory:',output)
    print('Demo credentials only.' if args.demo else 'Credentials remain local. Do not publish the build folder or firmware.')


if __name__ == '__main__':
    main()
