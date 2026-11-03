"""Restore offset 0 only when the same unit's SS1 and stock DS1 are intact."""
import hashlib

from qsl1sec.image import validate_snapshot, EEPROM_SIZE
from . import RecoveryError
from . import captures
from .serial_link import WP_PIN, WP_CONFIG, WP_CALLBACK, ROM_CALLBACK, ROM_REGIONS, ROM_FINGERPRINTS


def expected_image(original, current):
    validate_snapshot(original)
    validate_snapshot(current, require_stock_selected=False)
    if current[0] not in (0, 1):
        raise RecoveryError('Unrecognized SS1 marker; this kit only supports 00/01')
    if current[1:40] != original[1:40]:
        raise RecoveryError('SS1 configuration/identity differs from the original backup')
    # validate_snapshot checks the fixed stock DS hash in both images.
    # Keep all owner/settings/log/SS2/DS2 bytes from CURRENT, not the old image.
    return b'\1' + current[1:]


class RomWriteProtect:
    def __init__(self, hci, journal):
        self.hci, self.journal = hci, journal
        self.pin_attempted = self.callback_attempted = False

    def enable(self):
        for (address, length), fingerprint in zip(ROM_REGIONS, ROM_FINGERPRINTS):
            if hashlib.sha256(self.hci.read_region(address, length)).hexdigest() != fingerprint:
                raise RecoveryError('ROM fingerprint differs; no RAM/EEPROM write sent')
        if self.hci.read_memory(WP_PIN, 1) != b'\xff' or self.hci.read_memory(WP_CONFIG, 8) != b'\x10\0\0\0\0\0\0\0':
            raise RecoveryError('ROM-mode WP/page configuration differs; no write sent')
        self.journal.update(stage='before-wp-setup')
        self.pin_attempted = True
        self.hci.write_runtime(WP_PIN, b'\1')
        self.callback_attempted = True
        self.hci.write_runtime(WP_CALLBACK, ROM_CALLBACK)
        self.journal.update(stage='wp-enabled')

    def restore(self):
        errors = []
        for attempted, address, data in ((self.callback_attempted, WP_CALLBACK, bytes(4)),
                                         (self.pin_attempted, WP_PIN, b'\xff')):
            if attempted:
                try:
                    self.hci.write_runtime(address, data)
                except BaseException as error:
                    errors.append(type(error).__name__)
        self.journal.update(runtime_settings_restored=not errors)
        if errors:
            raise RecoveryError('Temporary WP settings could not be verified restored; stop and inspect')


def two_passes(hci, directory, password, prefix, progress=print):
    results = []
    for number in (1, 2):
        progress(f'{prefix}: read pass {number}/2 (65536 bytes)')
        data = hci.read_eeprom()
        captures.save(directory / f'{prefix}-pass{number}.qsb', data, password)
        results.append(data)
    if results[0] != results[1]:
        raise RecoveryError('Independent EEPROM reads differ; both encrypted captures preserved')
    return results[0]


def restore_stock(hci, original, snapshot, directory, password, progress=print):
    expected = expected_image(original, snapshot)
    journal = captures.Journal(directory)
    protect = RomWriteProtect(hci, journal)
    try:
        hci.require_version()
        current = two_passes(hci, directory, password, 'before', progress)
        if current != snapshot:
            raise RecoveryError('Live EEPROM differs from the supplied snapshot; no write sent')
        journal.update(stage='two-live-backups-verified')
        if current == expected:
            journal.update(stage='already-stock-selected', marker_readback_verified=True,
                           runtime_settings_restored=True, completed=True)
            return journal.record
        # Grant writes only after durable, verified independent backups.
        hci.allow_writes = True
        try:
            protect.enable()
            journal.update(stage='before-marker-write', marker_write_attempted=True)
            hci.write_stock_marker()  # Exactly one persistent write attempt.
            journal.update(stage='marker-acknowledged')
            after = hci.read_eeprom()
            captures.save(directory / 'after-marker.qsb', after, password)
            if after != expected:
                raise RecoveryError('Full readback differs from the one-byte plan; no automatic retry')
            journal.update(stage='full-readback-verified', marker_readback_verified=True,
                           all_other_bytes_unchanged=True)
        finally:
            try:
                protect.restore()
            finally:
                hci.allow_writes = False
        journal.update(stage='selector-restored-awaiting-normal-boot', completed=True)
        progress('Selector verified. Disconnect UART and check battery-only boot separately.')
        return journal.record
    except BaseException as error:
        journal.update(stage='stopped', error_type=type(error).__name__, completed=False)
        raise
