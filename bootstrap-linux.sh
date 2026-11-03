#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "$0")"
if [[ "$(uname -s)" != Linux ]]; then
  echo 'The wireless installer requires Linux/BlueZ.' >&2
  exit 1
fi
if [[ ${EUID} -eq 0 ]]; then
  echo 'Run this dependency-setup script as your normal user. Use sudo only for the BLE commands in the guide.' >&2
  exit 1
fi
python3 -m venv .venv
.venv/bin/python -m pip install -r requirements-linux.txt
mkdir -p .private
chmod 700 .private
.venv/bin/python -m qsl1sec --help
echo 'Dependencies prepared. No Bluetooth command or firmware write has been sent.'
