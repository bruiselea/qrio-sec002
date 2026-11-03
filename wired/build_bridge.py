"""Compile the fixed C3 binary bridge locally; never upload or open a port."""
import argparse
import json
import os
from pathlib import Path
import shutil
import subprocess

CORE_VERSION = '3.3.7'
FQBN = 'esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashSize=4M,FlashMode=dio,DebugLevel=none'


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--cli', default='arduino-cli')
    parser.add_argument('--config', type=Path, help='Optional private Arduino CLI config')
    parser.add_argument('--output-dir', type=Path, required=True, help='New private build directory')
    args = parser.parse_args(argv)
    cli = shutil.which(args.cli)
    if cli is None:
        parser.error('Arduino CLI not found; pass --cli or add it to PATH')
    command = [cli] + (['--config-file', str(args.config.resolve())] if args.config else [])
    result = subprocess.run(command + ['core', 'list', '--format', 'json'], capture_output=True, text=True, check=True)
    cores = json.loads(result.stdout).get('platforms', [])
    if not any(core.get('id') == 'esp32:esp32' and core.get('installed_version') == CORE_VERSION for core in cores):
        parser.error('Install esp32:esp32@3.3.7 first; no device was opened')
    output = args.output_dir.resolve()
    output.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    output.mkdir(mode=0o700)
    temporary = output / 'temp'; temporary.mkdir()
    environment = dict(os.environ)
    environment.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    subprocess.run(command + ['compile', '--fqbn', FQBN, '--build-path', str(output / 'build'),
                              '--output-dir', str(output / 'firmware'),
                              str(Path(__file__).resolve().with_name('c3_uart_bridge'))],
                   env=environment, check=True)
    print('Bridge compiled locally; no serial port opened and no device flashed.')


if __name__ == '__main__':
    main()
