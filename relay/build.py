"""Compile using ESPHome's managed IDF, without changing host-wide settings."""
import argparse
import os
from pathlib import Path
import subprocess
import sys

parser = argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config', required=True)
parser.add_argument('--action', choices=('compile', 'upload'), default='compile')
parser.add_argument('--device', help='USB serial port or OTA address, required for upload')
args = parser.parse_args()
if args.action == 'upload' and not args.device:
    parser.error('--device is required for upload')
environment = os.environ.copy()
ceilings = environment.get('GIT_CEILING_DIRECTORIES', '')
environment['GIT_CEILING_DIRECTORIES'] = os.pathsep.join(filter(None, [ceilings, str(Path(__file__).resolve().parents[2])]))
for key in ('IDF_PATH', 'IDF_TOOLS_PATH', 'IDF_PYTHON_ENV_PATH', 'IDF_TARGET', 'PYTHONPATH'):
    environment.pop(key, None)
if os.name == 'nt':
    # Keep framework downloads, .part files and extraction on the same volume.
    cache = Path(os.environ.get('ESPHOME_ESP_IDF_PREFIX') or (Path.home() / '.qrio-sl1' / 'build-tools'))
    temporary = cache / 'tmp'
    temporary.mkdir(parents=True, exist_ok=True)
    environment['ESPHOME_ESP_IDF_PREFIX'] = str(cache)
    environment['TEMP'] = environment['TMP'] = str(temporary)
command = [sys.executable, '-m', 'esphome', args.action, args.config]
if args.device:
    command += ['--device', args.device]
raise SystemExit(subprocess.call(command, env=environment))
