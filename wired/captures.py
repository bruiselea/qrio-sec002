"""Portable encrypted EEPROM captures; compatible with wireless original.qsb."""
import base64
import json
import os
from pathlib import Path
import tempfile

from qsl1sec import private
from qsl1sec.image import digest, EEPROM_SIZE
from . import RecoveryError


def payload(data):
    if len(data) != EEPROM_SIZE:
        raise RecoveryError('A complete 64 KiB EEPROM capture is required')
    return {'kind': 'owned-eeprom-64k', 'transport': 'uart', 'bytes': len(data),
            'sha256': digest(data), 'eeprom_b64': base64.b64encode(data).decode('ascii')}


def save(path, data, password):
    private.save(path, payload(data), password)
    sync_directory(Path(path).parent)


def sync_directory(path):
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def load(path, password):
    record = private.load(path, password)
    if record.get('kind') != 'owned-eeprom-64k':
        raise RecoveryError('Not a full EEPROM backup')
    data = base64.b64decode(record['eeprom_b64'], validate=True)
    if len(data) != EEPROM_SIZE or record.get('bytes') != EEPROM_SIZE or record.get('sha256') != digest(data):
        raise RecoveryError('EEPROM backup size/integrity mismatch')
    return data


def new_directory(path):
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    path.mkdir(mode=0o700)  # Existing output is never reused or overwritten.
    return path


class Journal:
    def __init__(self, directory):
        self.directory = Path(directory)
        self.path = self.directory / 'result.receipt.json'
        self.record = {'kind': 'qsl1-wired-stock-selector-v1', 'completed': False,
                       'marker_write_attempted': False, 'marker_readback_verified': False,
                       'runtime_settings_restored': False, 'normal_boot_verified': False,
                       'automatic_eeprom_write_retries': 0, 'erase_or_loader_commands': 0}
        self.update(stage='created')

    def update(self, **fields):
        self.record.update(fields)
        descriptor, name = tempfile.mkstemp(prefix='.receipt-', dir=self.directory)
        temporary = Path(name)
        try:
            with os.fdopen(descriptor, 'w', encoding='utf-8', newline='\n') as stream:
                json.dump(self.record, stream, sort_keys=True, indent=2)
                stream.write('\n')
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            sync_directory(self.directory)
        finally:
            temporary.unlink(missing_ok=True)
