import base64
import ctypes
from ctypes import wintypes
import hashlib
import io
import json
import os
from pathlib import Path
import struct
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

from qsl1sec import image, private
from wired import RecoveryError, captures, legacy, recovery
from wired.__main__ import main, parser
from wired.serial_link import (HCI, VERSION, ROM_REGIONS, ROM_FINGERPRINTS, ROM_CALLBACK,
                                WP_PIN, WP_CONFIG, WP_CALLBACK, EEPROM_BASE, EventParser, loopback, open_port)

PASSWORD = 'synthetic-wired-test-password'


def synthetic_original():
    data = bytearray(65536)
    for offset, kind, size in ((0, 1, 8), (11, 0xFD, 4), (18, 0x40, 6), (27, 2, 10)):
        struct.pack_into('<BH', data, offset, kind, size)
    data[21:27] = bytes.fromhex('001122334455')  # Synthetic SS identity.
    struct.pack_into('<I', data, 30, image.DS1)
    data[image.DS1:image.DS1 + image.DS_SIZE] = b'S' * image.DS_SIZE
    return bytes(data)


class FragmentedSerial:
    def __init__(self, reply=b'', short=False):
        self.reply = bytearray(reply)
        self.writes = []
        self.short = short
    def write(self, data):
        self.writes.append(data)
        return len(data) - int(self.short)
    def read(self, size):
        size = min(size, 1)
        result = bytes(self.reply[:size])
        del self.reply[:size]
        return result


class SimulatedHCI:
    """Emulates WP effects; EEPROM ACK is independent of actual write effect."""
    def __init__(self, data, fault=None):
        self.memory = bytes(data)
        self.allow_writes = False
        self.pin, self.callback = b'\xff', bytes(4)
        self.fault = fault
        self.persistent_attempts = self.ram_attempts = 0
        self.reads = 0
    def require_version(self): pass
    def read_eeprom(self):
        self.reads += 1
        if self.fault == 'unstable' and self.reads == 2:
            return self.memory[:-1] + bytes([self.memory[-1] ^ 1])
        return self.memory
    def read_region(self, address, length):
        return bytes([1 if address == ROM_REGIONS[0][0] else 2]) * length
    def read_memory(self, address, length):
        if address == WP_PIN: return self.pin
        if address == WP_CONFIG: return b'\x10\0\0\0' + self.callback
        if address == WP_CALLBACK: return self.callback
        raise AssertionError('unexpected read')
    def write_runtime(self, address, data):
        assert self.allow_writes
        self.ram_attempts += 1
        if address == WP_PIN: self.pin = data
        elif address == WP_CALLBACK: self.callback = data
        else: raise AssertionError('unexpected RAM write')
        if self.fault == 'enable-lost-ack' and data == ROM_CALLBACK:
            raise RecoveryError('synthetic RAM ACK loss')
        if self.fault == 'restore-lost-ack' and address == WP_PIN and data == b'\xff':
            raise RecoveryError('synthetic restoration ACK loss')
    def write_stock_marker(self):
        assert self.allow_writes and self.pin == b'\1' and self.callback == ROM_CALLBACK
        self.persistent_attempts += 1
        if self.fault != 'ack-no-effect': self.memory = b'\1' + self.memory[1:]
        if self.fault == 'collateral': self.memory = self.memory[:-1] + bytes([self.memory[-1] ^ 1])
        if self.fault == 'marker-lost-ack': raise RecoveryError('synthetic persistent ACK loss')


class PolicyTests(unittest.TestCase):
    def setUp(self):
        self.original = synthetic_original()
        self.snapshot = b'\0' + self.original[1:]
        self.patch = patch.object(image, 'STOCK_DS_SHA', image.digest(self.original[image.DS1:image.DS1 + image.DS_SIZE]))
        self.patch.start(); self.addCleanup(self.patch.stop)

    def test_only_marker_changes_and_ds2_owner_bytes_survive(self):
        data = bytearray(self.snapshot)
        data[0x100:0x128] = b'X' * 40
        data[0x8000:] = b'Y' * 0x8000
        expected = recovery.expected_image(self.original, bytes(data))
        self.assertEqual(expected, b'\1' + bytes(data[1:]))
        self.assertEqual(sum(a != b for a, b in zip(expected, data)), 1)

    def test_wrong_unit_corrupt_ss_ds_and_bad_marker_are_refused(self):
        for offset in (1, 21, 39, image.DS1, image.DS1 + image.DS_SIZE - 1):
            damaged = bytearray(self.snapshot); damaged[offset] ^= 1
            with self.subTest(offset=offset), self.assertRaises((ValueError, RecoveryError)):
                recovery.expected_image(self.original, bytes(damaged))
        for marker in (2, 255):
            with self.assertRaises(RecoveryError):
                recovery.expected_image(self.original, bytes([marker]) + self.snapshot[1:])
        with self.assertRaises(ValueError): recovery.expected_image(self.original, self.snapshot[:-1])

    def test_already_selected_is_noop(self):
        self.assertEqual(recovery.expected_image(self.original, self.original), self.original)

    def test_arbitrary_ds2_damage_does_not_require_ds2_rewrite(self):
        # Interrupted staging at every 16-byte boundary; SS2 can also be partial.
        data = bytearray(self.snapshot)
        data[0x100:0x128] = b'\xff' * 40
        for stop in range(0, image.DS_SIZE, 16):
            data[0x8000 + stop:0x8000 + min(stop + 16, image.DS_SIZE)] = b'Z' * min(16, image.DS_SIZE - stop)
            expected = recovery.expected_image(self.original, bytes(data))
            self.assertEqual(expected[1:], data[1:])


class SerialTests(unittest.TestCase):
    def test_complete_serial_recovery_contract_uses_only_fixed_hci_writes(self):
        original = synthetic_original()
        snapshot = b'\0' + original[1:]
        class Device(FragmentedSerial):
            def __init__(inner):
                super().__init__()
                inner.memory = snapshot
                inner.pin, inner.callback = b'\xff', bytes(4)
            def write(inner, frame):
                inner.writes.append(frame)
                self.assertEqual(frame[0], 1)
                opcode, length = struct.unpack_from('<HB', frame, 1)
                payload = frame[4:]
                self.assertEqual(length, len(payload))
                if opcode == 0x1001:
                    result = struct.pack('<BHBHH', *VERSION)
                elif opcode == 0xFC4D:
                    address, size = struct.unpack('<IB', payload)
                    if address >= EEPROM_BASE:
                        result = inner.memory[address - EEPROM_BASE:address - EEPROM_BASE + size]
                    elif address == WP_PIN: result = inner.pin
                    elif address == WP_CONFIG: result = b'\x10\0\0\0' + inner.callback
                    elif address == WP_CALLBACK: result = inner.callback
                    else:
                        region = next((i for i, (base, count) in enumerate(ROM_REGIONS)
                                       if base <= address and address + size <= base + count), None)
                        self.assertIsNotNone(region)
                        result = bytes([region + 1]) * size
                elif opcode == 0xFC4C:
                    address, = struct.unpack_from('<I', payload)
                    if address == WP_PIN: inner.pin = payload[4:]
                    elif address == WP_CALLBACK: inner.callback = payload[4:]
                    elif address == EEPROM_BASE:
                        self.assertEqual((inner.pin, inner.callback), (b'\1', ROM_CALLBACK))
                        self.assertEqual(payload[4:], b'\1')
                        inner.memory = b'\1' + inner.memory[1:]
                    else: self.fail('unexpected persistent write')
                    result = b''
                else: self.fail('unsupported command')
                parameters = b'\1' + struct.pack('<H', opcode) + b'\0' + result
                inner.reply.extend(b'\4\x0e' + bytes([len(parameters)]) + parameters)
                return len(frame)
        fingerprints = tuple(hashlib.sha256(bytes([i + 1]) * length).hexdigest()
                             for i, (_, length) in enumerate(ROM_REGIONS))
        device = Device()
        with tempfile.TemporaryDirectory() as directory, \
             patch.object(image, 'STOCK_DS_SHA', image.digest(original[image.DS1:image.DS1 + image.DS_SIZE])), \
             patch.object(recovery, 'ROM_FINGERPRINTS', fingerprints):
            result = recovery.restore_stock(HCI(device), original, snapshot, Path(directory), PASSWORD, lambda _: None)
        self.assertTrue(result['completed'])
        self.assertEqual(device.memory, original)
        writes = [frame for frame in device.writes if frame[1:3] == b'\x4c\xfc']
        self.assertEqual(len(writes), 5)  # Two WP changes, marker, two restorations.
        self.assertEqual(sum(frame[4:8] == struct.pack('<I', EEPROM_BASE) for frame in writes), 1)
        self.assertEqual((device.pin, device.callback), (b'\xff', bytes(4)))

    def test_fragmented_version_reply(self):
        body = b'\1\1\x10\0' + struct.pack('<BHBHH', *VERSION)
        connection = FragmentedSerial(b'\4\x0e' + bytes([len(body)]) + body)
        self.assertEqual(HCI(connection).version(), VERSION)
        self.assertEqual(connection.writes, [b'\1\1\x10\0'])

    def test_rejections_short_write_timeout_and_echo_do_not_retry(self):
        cases = (FragmentedSerial(b'\4\x0e\4\1\1\x10\x0c'),
                 FragmentedSerial(b'\4\x0f\4\x0c\1\1\x10'),
                 FragmentedSerial(short=True), FragmentedSerial(b'\1\1\x10\0'))
        for connection in cases:
            with self.assertRaises(RecoveryError): HCI(connection).version()
            self.assertEqual(len(connection.writes), 1)
        connection = FragmentedSerial()
        with patch('wired.serial_link.time.monotonic', side_effect=[0, 5]):
            with self.assertRaises(RecoveryError): HCI(connection).version()
        self.assertEqual(len(connection.writes), 1)

    def test_read_write_ranges_refused_before_sending(self):
        connection = FragmentedSerial()
        hci = HCI(connection)
        for address, length in ((EEPROM_BASE - 1, 1), (EEPROM_BASE + 65535, 2),
                                (EEPROM_BASE, 65), (0x200000, 1), (WP_PIN, 2), (True, 1)):
            with self.assertRaises(RecoveryError): hci.read_memory(address, length)
        with self.assertRaises(RecoveryError): hci.write_runtime(WP_PIN, b'\1')
        hci.allow_writes = True
        for address, data in ((EEPROM_BASE + 1, b'\1'), (WP_PIN, b'\2'), (WP_CALLBACK, b'x' * 4)):
            with self.assertRaises(RecoveryError): hci._request(0xFC4C, struct.pack('<I', address) + data)
        self.assertEqual(connection.writes, [])

    def test_marker_ack_without_physical_effect_is_rejected(self):
        hci = HCI(FragmentedSerial(), allow_writes=True)
        hci.read_memory = Mock(side_effect=[b'\1', ROM_CALLBACK, bytes(16)])
        hci._request = Mock(return_value=b'')
        with self.assertRaises(RecoveryError): hci.write_stock_marker()
        hci._request.assert_called_once_with(0xFC4C, struct.pack('<I', EEPROM_BASE) + b'\1')

    def test_parser_rejects_unframed_or_excessive_input(self):
        with self.assertRaises(RecoveryError): EventParser().feed(b'not HCI')
        with self.assertRaises(RecoveryError): EventParser().feed(bytes(2049))

    def test_non_usb_and_wrong_c3_ports_are_never_opened(self):
        wrong = SimpleNamespace(device='synthetic-port', vid=1, pid=2)
        with patch('serial.tools.list_ports.comports', return_value=[wrong]), patch('serial.Serial') as constructor:
            with self.assertRaises(RecoveryError): open_port(wrong.device)
            constructor.assert_not_called()
            wrong.vid = wrong.pid = None
            with self.assertRaises(RecoveryError): open_port(wrong.device, 'uart-3v3')
            constructor.assert_not_called()

    def test_loopback_all_bytes_and_corruption(self):
        class Echo(FragmentedSerial):
            def reset_input_buffer(inner): inner.reply.clear()
            def write(inner, data):
                inner.reply.extend(data)
                return super().write(data)
        self.assertEqual(loopback(Echo(), 4096)['loopback_bytes_verified'], 4096)
        broken = Echo(); broken.short = True
        with self.assertRaises(RecoveryError): loopback(broken, 256)
        self.assertEqual(len(broken.writes), 1)


class CaptureTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'capture.qsb'

    def test_portable_capture_compatible_with_existing_wireless_format(self):
        data = synthetic_original()
        captures.save(self.path, data, PASSWORD)
        self.assertEqual(captures.load(self.path, PASSWORD), data)
        with self.assertRaises(ValueError): captures.load(self.path, 'wrong-passphrase')
        with self.assertRaises(FileExistsError): captures.save(self.path, data, PASSWORD)
        if os.name == 'posix': self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)

    def test_wireless_backup_can_be_read_without_ble_dependency(self):
        data = synthetic_original()
        payload = captures.payload(data)
        payload.update(address='synthetic-address', identity='synthetic-identity')
        private.save(self.path, payload, PASSWORD)
        self.assertEqual(captures.load(self.path, PASSWORD), data)

    def test_output_directory_is_never_reused(self):
        directory = Path(self.temp.name) / 'new-output'
        captures.new_directory(directory)
        with self.assertRaises(FileExistsError): captures.new_directory(directory)

    def test_malformed_legacy_envelope_is_refused_without_decryption(self):
        self.path.write_text(json.dumps({'format': 'wrong', 'bytes': 65536}))
        with patch.object(legacy, 'unprotect') as decrypt:
            with self.assertRaises(RecoveryError): legacy.read_legacy(self.path)
            decrypt.assert_not_called()

    @unittest.skipUnless(sys.platform == 'win32', 'Windows DPAPI only')
    def test_dpapi_conversion_with_synthetic_memory_only(self):
        class Blob(ctypes.Structure):
            _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
        data = synthetic_original()
        backing = ctypes.create_string_buffer(data)
        source = Blob(len(data), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte)))
        output = Blob()
        crypt, kernel = ctypes.WinDLL('crypt32'), ctypes.WinDLL('kernel32')
        crypt.CryptProtectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p, ctypes.c_void_p,
                                            ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
        crypt.CryptProtectData.restype = wintypes.BOOL
        kernel.LocalFree.argtypes = [ctypes.c_void_p]
        self.assertTrue(crypt.CryptProtectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)))
        try: protected = ctypes.string_at(output.data, output.size)
        finally: kernel.LocalFree(output.data)
        self.path.write_text(json.dumps({'format': 'qrio-sl1-firmware-dpapi-v1', 'bytes': 65536,
                            'sha256': hashlib.sha256(data).hexdigest(), 'protected': base64.b64encode(protected).decode()}))
        self.assertEqual(legacy.read_legacy(self.path), data)


class TransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.directory = Path(self.temp.name)
        self.original = synthetic_original()
        self.snapshot = b'\0' + self.original[1:]
        self.patches = (patch.object(image, 'STOCK_DS_SHA', image.digest(self.original[image.DS1:image.DS1 + image.DS_SIZE])),
                        patch.object(recovery, 'ROM_FINGERPRINTS', tuple(hashlib.sha256(bytes([i + 1]) * length).hexdigest()
                                      for i, (_, length) in enumerate(ROM_REGIONS))))
        for setting in self.patches: setting.start(); self.addCleanup(setting.stop)

    def run_recovery(self, hci):
        return recovery.restore_stock(hci, self.original, self.snapshot, self.directory, PASSWORD, lambda _: None)

    def test_success_preserves_every_other_byte_and_restores_wp(self):
        hci = SimulatedHCI(self.snapshot)
        result = self.run_recovery(hci)
        self.assertTrue(result['completed'] and result['marker_readback_verified'])
        self.assertFalse(result['normal_boot_verified'])
        self.assertEqual(hci.memory, self.original)
        self.assertEqual(hci.persistent_attempts, 1)
        self.assertEqual((hci.pin, hci.callback), (b'\xff', bytes(4)))
        self.assertEqual(captures.load(self.directory / 'before-pass1.qsb', PASSWORD), self.snapshot)
        self.assertEqual(captures.load(self.directory / 'before-pass2.qsb', PASSWORD), self.snapshot)
        self.assertEqual(captures.load(self.directory / 'after-marker.qsb', PASSWORD), self.original)

    def test_changed_live_or_unstable_reads_prevent_all_writes(self):
        for index, fault in enumerate(('changed', 'unstable')):
            self.directory = Path(self.temp.name) / str(index); self.directory.mkdir()
            data = self.snapshot[:-1] + b'X' if fault == 'changed' else self.snapshot
            hci = SimulatedHCI(data, fault)
            with self.assertRaises(RecoveryError): self.run_recovery(hci)
            self.assertEqual((hci.persistent_attempts, hci.ram_attempts), (0, 0))

    def test_rom_or_runtime_mismatch_blocks_writes(self):
        for index, field in enumerate(('rom', 'pin', 'callback')):
            self.directory = Path(self.temp.name) / str(index); self.directory.mkdir()
            hci = SimulatedHCI(self.snapshot)
            if field == 'rom': hci.read_region = lambda a, n: bytes(n)
            elif field == 'pin': hci.pin = b'\1'
            else: hci.callback = ROM_CALLBACK
            with self.assertRaises(RecoveryError): self.run_recovery(hci)
            self.assertEqual((hci.persistent_attempts, hci.ram_attempts), (0, 0))

    def test_lost_ack_no_effect_collateral_and_cleanup_failure_never_replay(self):
        for index, fault in enumerate(('marker-lost-ack', 'ack-no-effect', 'collateral', 'restore-lost-ack', 'enable-lost-ack')):
            self.directory = Path(self.temp.name) / str(index); self.directory.mkdir()
            hci = SimulatedHCI(self.snapshot, fault)
            with self.subTest(fault=fault), self.assertRaises(RecoveryError): self.run_recovery(hci)
            self.assertLessEqual(hci.persistent_attempts, 1)
            self.assertFalse(hci.allow_writes)
            self.assertEqual((hci.pin, hci.callback), (b'\xff', bytes(4)))
            result = json.loads((self.directory / 'result.receipt.json').read_text())
            self.assertFalse(result['completed'])

    def test_backup_failure_prevents_ram_and_eeprom_writes(self):
        hci = SimulatedHCI(self.snapshot)
        with patch.object(captures, 'save', side_effect=OSError('synthetic full disk')):
            with self.assertRaises(OSError): self.run_recovery(hci)
        self.assertEqual((hci.persistent_attempts, hci.ram_attempts), (0, 0))

    def test_journal_failure_before_marker_blocks_persistent_write_and_cleans_wp(self):
        hci = SimulatedHCI(self.snapshot)
        real = captures.Journal.update
        def fail(journal, **fields):
            if fields.get('stage') == 'before-marker-write': raise OSError('synthetic journal failure')
            return real(journal, **fields)
        with patch.object(captures.Journal, 'update', fail):
            with self.assertRaises(OSError): self.run_recovery(hci)
        self.assertEqual(hci.persistent_attempts, 0)
        self.assertEqual((hci.pin, hci.callback), (b'\xff', bytes(4)))


class CLITests(unittest.TestCase):
    def test_execute_missing_physical_preparation_never_opens_serial(self):
        with patch('wired.__main__.open_port') as opening, patch('builtins.print'):
            self.assertEqual(main(['restore-stock', '--original', 'synthetic.qsb', '--snapshot', 'synthetic.qsb', '--execute']), 1)
            opening.assert_not_called()

    def test_offline_plan_does_not_open_serial(self):
        with patch('wired.__main__.captures.load', side_effect=[b'a', b'b']), \
             patch('wired.__main__.hidden', return_value=PASSWORD), \
             patch('wired.__main__.expected_image', return_value=b'c'), \
             patch('wired.__main__.open_port') as opening, patch('builtins.print'):
            self.assertEqual(main(['restore-stock', '--original', 'synthetic.qsb', '--snapshot', 'synthetic.qsb']), 0)
            opening.assert_not_called()

    def test_loopback_requires_explicit_target_disconnected(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit): parser().parse_args(['loopback', '--port', 'synthetic'])

    def test_exception_details_are_not_echoed(self):
        with patch('wired.__main__.run', side_effect=OSError('SECRET-DO-NOT-PRINT')), \
             patch('sys.stdout', new_callable=io.StringIO) as output:
            self.assertEqual(main(['ports']), 1)
        self.assertNotIn('SECRET-DO-NOT-PRINT', output.getvalue())


if __name__ == '__main__':
    unittest.main()
