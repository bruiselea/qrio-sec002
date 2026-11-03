import asyncio
import base64
import copy
import hashlib
import io
import json
import os
from pathlib import Path
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, patch
import uuid
import warnings
import zipfile

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

from onboarding import EnrollmentError
from onboarding import mq, vault, enrollment
from onboarding.__main__ import hidden, main, parser
from onboarding.runtime import QrioLive, discover, protocol

SERIAL = 'S01-0ABCDEF-Z'  # Fabricated identity, not an owner card.
IDENTITY = bytes(range(16))
PASSWORD = 'synthetic-test-passphrase'
ADVERTISEMENT = protocol.LockAdvertisement(None, 'S01-0ABCDEF', IDENTITY)
# An artificial algebra table, not the table from an APK.
COEFFICIENTS = bytes((index * 29 + index // 16) % 256 for index in range(mq.COEFFICIENT_BYTES))


def pem(key):
    return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                             serialization.NoEncryption()).decode('ascii')


def legacy_blob(record, password):
    """Independent reproduction of the previously used v1 envelope writer."""
    salt, nonce = bytes(range(16)), bytes(range(12))
    key = Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode('utf-8'))
    cipher = AESGCM(key).encrypt(nonce, json.dumps(record).encode(), b'qrio-sl1-owner-credential-v1')
    return json.dumps({'format': 'qrio-sl1-owner-credential-v1', 'salt': base64.b64encode(salt).decode(),
                       'nonce': base64.b64encode(nonce).decode(),
                       'ciphertext': base64.b64encode(cipher).decode()}).encode()


class RecordFixture:
    @classmethod
    def setUpClass(cls):
        cls.record = enrollment.prepare_record(ADVERTISEMENT, SERIAL, COEFFICIENTS)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.path = Path(self.temp.name) / 'owner.qsl1'
        self.owner = copy.deepcopy(self.record)


class MQTests(unittest.TestCase):
    def test_zero_and_word_endian_across_all_boundaries(self):
        self.assertEqual(mq.public_from_private(bytes(16), COEFFICIENTS), bytes(16))
        for bits in ((0,), (7,), (31,), (32,), (63,), (127,), (0, 31), (31, 32), (0, 127)):
            words = [0] * 4
            for bit in bits:
                words[bit // 32] |= 1 << (bit % 32)
            key = b''.join(word.to_bytes(4, 'big') for word in words)
            expected = bytearray(16)
            for high in bits:
                for low in bits:
                    if low <= high:
                        start = (high * (high + 1) // 2 + low) * 16
                        for byte in range(16):
                            expected[byte] ^= COEFFICIENTS[start + byte]
            expected = b''.join(expected[start:start + 4][::-1] for start in range(0, 16, 4))
            self.assertEqual(mq.public_from_private(key, COEFFICIENTS), expected)

    def test_bad_mq_sizes(self):
        for key, table in ((b'', COEFFICIENTS), (bytes(16), b''), (bytes(17), COEFFICIENTS)):
            with self.assertRaises(ValueError):
                mq.public_from_private(key, table)

    def test_apk_rejects_missing_unknown_duplicate_and_oversized_library(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'synthetic.apk'
            for entries in ([], [(mq.LIBRARY_PATH, b'untrusted')],
                            [(mq.LIBRARY_PATH, b'a'), (mq.LIBRARY_PATH, b'b')],
                            [(mq.LIBRARY_PATH, bytes(4 * 1024 * 1024 + 1))]):
                with warnings.catch_warnings():
                    warnings.simplefilter('ignore', UserWarning)
                    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
                        for name, data in entries:
                            archive.writestr(name, data)
                with self.assertRaises(ValueError):
                    mq.load_coefficients(path)

    def test_apk_bounds_and_empty(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / 'empty.apk'
            path.touch()
            with self.assertRaises(ValueError):
                mq.load_coefficients(path)
            with path.open('wb') as output:
                output.truncate(150 * 1024 * 1024 + 1)
            with self.assertRaises(ValueError):
                mq.load_coefficients(path)


class VaultTests(RecordFixture, unittest.TestCase):
    def test_unicode_roundtrip_and_legacy_v1(self):
        password = ' 日本語の試験ですＡｂＣ  '
        self.assertEqual(vault.decrypt_vault(legacy_blob(self.owner, password), password), self.owner)
        vault.create_vault(self.path, self.owner, password)
        self.assertEqual(vault.read_vault(self.path, password), self.owner)
        with self.assertRaises(ValueError):
            vault.read_vault(self.path, password.strip())

    def test_wrong_password_and_tamper_and_envelope_bounds(self):
        blob = vault.encrypt_vault(self.owner, PASSWORD)
        with self.assertRaises(ValueError):
            vault.decrypt_vault(blob, 'wrong-password')
        for field in ('salt', 'nonce', 'ciphertext'):
            envelope = json.loads(blob)
            data = bytearray(base64.b64decode(envelope[field])); data[0] ^= 1
            envelope[field] = base64.b64encode(data).decode()
            with self.assertRaises(ValueError):
                vault.decrypt_vault(json.dumps(envelope).encode(), PASSWORD)
        for invalid in (b'', b'[]', b'x' * (vault.MAX_BLOB + 1)):
            with self.assertRaises(ValueError):
                vault.decrypt_vault(invalid, PASSWORD)

    def test_create_and_export_never_overwrite(self):
        vault.create_vault(self.path, self.owner, PASSWORD)
        before = self.path.read_bytes()
        with self.assertRaises(FileExistsError):
            vault.create_vault(self.path, self.owner, PASSWORD)
        self.assertEqual(self.path.read_bytes(), before)
        self.owner.update(state='verified', verification='authenticated-read-status-v1')
        output = Path(self.temp.name) / 'owner.json'
        vault.export_owner(self.owner, output)
        with self.assertRaises(FileExistsError):
            vault.export_owner(self.owner, output)
        self.assertEqual(self.path.read_bytes(), before)

    def test_export_minimal_fields_and_runtime_compatibility(self):
        self.owner.update(state='verified', verification='authenticated-read-status-v1')
        output = Path(self.temp.name) / 'owner.json'
        vault.export_owner(self.owner, output)
        record = json.loads(output.read_bytes())
        self.assertEqual(set(record), set(vault.EXPORT_FIELDS))
        self.assertEqual(record['state'], 'registered')
        self.assertNotIn('mq_private', record)
        self.assertNotIn('storage_private_pem', record)
        self.assertNotIn('serial', record)
        self.assertEqual(QrioLive(record).phone_id, protocol.uuid_bytes(uuid.UUID(self.owner['phone_uuid'])))
        if os.name == 'posix':
            self.assertEqual(output.stat().st_mode & 0o777, 0o600)

    def test_unverified_ack_and_old_registered_cannot_export(self):
        for state in ('pending', 'acknowledged', 'registered', 'verified'):
            self.owner['state'] = state
            with self.assertRaises(ValueError):
                vault.export_owner(self.owner, Path(self.temp.name) / 'owner.json')

    def test_update_preserves_previous_ciphertext_and_private_modes(self):
        vault.create_vault(self.path, self.owner, PASSWORD)
        previous = self.path.read_bytes()
        self.owner['state'] = 'acknowledged'
        vault.update_vault(self.path, self.owner, PASSWORD)
        backups = list(self.path.parent.glob('*.backup-*'))
        self.assertEqual(len(backups), 1)
        self.assertEqual(backups[0].read_bytes(), previous)
        self.assertEqual(vault.read_vault(self.path, PASSWORD), self.owner)
        if os.name == 'posix':
            self.assertEqual(self.path.stat().st_mode & 0o777, 0o600)
            self.assertEqual(backups[0].stat().st_mode & 0o777, 0o600)

    def test_interrupted_atomic_replace_keeps_original_and_backup(self):
        vault.create_vault(self.path, self.owner, PASSWORD)
        previous = self.path.read_bytes()
        self.owner['state'] = 'acknowledged'
        with patch.object(vault.os, 'replace', side_effect=OSError('synthetic disk failure')):
            with self.assertRaises(OSError):
                vault.update_vault(self.path, self.owner, PASSWORD)
        self.assertEqual(self.path.read_bytes(), previous)
        self.assertEqual(len(list(self.path.parent.glob('*.backup-*'))), 1)
        self.assertEqual(list(self.path.parent.glob('.qsl1-*')), [])

    def test_lock_rejects_concurrent_process_and_releases(self):
        import subprocess
        import sys
        script = ('from onboarding.vault import vault_lock; from pathlib import Path; '
                  'import sys;\nwith vault_lock(Path(sys.argv[1])): pass\n')
        with vault.vault_lock(self.path):
            result = subprocess.run([sys.executable, '-c', script, str(self.path)], capture_output=True)
            self.assertNotEqual(result.returncode, 0)
        result = subprocess.run([sys.executable, '-c', script, str(self.path)], capture_output=True)
        self.assertEqual(result.returncode, 0)

    def test_record_validation_rejects_key_and_identity_damage(self):
        vault.validate_record(self.owner, COEFFICIENTS)
        for field, value in (('mq_public', '00' * 16), ('challenge_a', 'xx' * 16),
                             ('phone_uuid', 'bad'), ('signing_private_pem', 'not a key'),
                             ('lock_uuid', ''), ('version', True)):
            damaged = dict(self.owner); damaged[field] = value
            with self.assertRaises((ValueError, TypeError)):
                vault.validate_record(damaged, COEFFICIENTS)


class SimulatedLock:
    """Independent protocol peer that decrypts/verifies the complete exchange."""
    def __init__(self, test, record, path, fail_at=None, wrong_card=False):
        self.test, self.record, self.path = test, record, path
        self.fail_at, self.wrong_card = fail_at, wrong_card
        self.card = bytes(range(16))
        self.client = self
        self.queue = asyncio.Queue()
        self.frames = []
        self.messages = []
        self.la, self.lb, self.nonce = b'A' * 16, b'B' * 16, b'N' * 32

    async def write_gatt_char(self, characteristic, frame, response=False):
        self.test.assertFalse(response)
        self.test.assertEqual(characteristic, protocol.WRITE_UUIDS[len(self.frames) % 4])
        self.test.assertEqual(len(frame), 20)
        self.frames.append(frame)
        if len(self.frames) != (self.frames[0][0] & 127):
            return
        queue = asyncio.Queue()
        for packet in self.frames:
            queue.put_nowait(packet)
        body = await protocol.receive_message(queue)
        self.frames.clear()
        step = body[:2]
        self.messages.append(step)
        saved = vault.read_vault(self.path, PASSWORD)
        for field in ('phone_uuid', 'signing_private_pem', 'mq_private', 'challenge_a', 'challenge_b'):
            self.test.assertEqual(saved[field], self.record[field])
        phone = protocol.uuid_bytes(uuid.UUID(self.record['phone_uuid']))
        a, b = [bytes.fromhex(self.record[field]) for field in ('challenge_a', 'challenge_b')]
        if step == b'\x01\x00':
            self.test.assertEqual(body[2:18], phone)
            decryptor = Cipher(algorithms.AES(self.card), modes.ECB()).decryptor()
            self.test.assertEqual(decryptor.update(body[18:]) + decryptor.finalize(), a + b)
            reply = b'\0\0' + self.la + self.lb
        elif step == b'\x01\x01':
            pa, pb = body[2:18], body[18:34]
            self.test.assertEqual(body[34:66], protocol.mac(a, enrollment.CONTEXT, b'\0', pa, self.la, IDENTITY, phone))
            self.test.assertEqual(body[66:], protocol.mac(b, enrollment.CONTEXT, b'\0', pb, self.lb, IDENTITY, phone))
            reply = (b'\0' + protocol.mac(a, enrollment.CONTEXT, b'\0', self.la, pa, phone, IDENTITY)
                     + protocol.mac(b, enrollment.CONTEXT, b'\0', self.lb, pb, phone, IDENTITY))
            if self.wrong_card:
                reply = b'\0' + bytes(64)
        elif step == b'\x01\x02':
            self.test.assertEqual(saved['phase'], 'before-public-key')
            self.test.assertEqual(len(body), 307)
            modulus, public = body[2:259], body[259:275]
            self.test.assertEqual(public.hex(), self.record['mq_public'])
            self.test.assertEqual(body[275:], protocol.mac(b, enrollment.CONTEXT, b'\0', modulus, public))
            self.public = rsa.RSAPublicNumbers(65537, int.from_bytes(modulus, 'big')).public_key()
            reply = b'\0' + self.nonce
        elif step == b'\x01\x03':
            self.test.assertEqual(saved['phase'], 'before-confirmation')
            self.test.assertEqual(len(body), 290)
            self.public.verify(body[34:], enrollment.CONTEXT + b'\1' + body[2:34] + self.nonce + IDENTITY + phone,
                               padding.PKCS1v15(), hashes.SHA256())
            reply = b'\0'
        elif step == b'\x01\x05':
            self.test.assertEqual(len(body), 2)
            reply = b'\0'
        else:
            self.test.fail('Unexpected command; firmware/motor operations must not appear')
        if step == self.fail_at:
            raise TimeoutError('synthetic response lost AFTER accepting a request')
        for packet in protocol.frame_message(reply):
            self.queue.put_nowait(packet)


class EnrollmentTests(RecordFixture, unittest.IsolatedAsyncioTestCase):
    def peer(self, **kwargs):
        vault.create_vault(self.path, self.owner, PASSWORD)
        return SimulatedLock(self, self.owner, self.path, **kwargs)

    async def test_full_card_exchange_acks_but_does_not_mark_verified(self):
        peer = self.peer()
        await enrollment.handshake(peer, peer.card, self.owner,
                                   lambda r: vault.update_vault(self.path, r, PASSWORD), lambda _: None)
        self.assertEqual(peer.messages, [b'\1\0', b'\1\1', b'\1\2', b'\1\3', b'\1\5'])
        self.assertEqual(vault.read_vault(self.path, PASSWORD)['state'], 'acknowledged')
        with self.assertRaises(ValueError):
            vault.export_owner(self.owner, self.path.parent / 'owner.json')

    async def test_card_proof_failure_stops_before_public_key_write(self):
        peer = self.peer(wrong_card=True)
        with self.assertRaises(EnrollmentError):
            await enrollment.handshake(peer, peer.card, self.owner,
                                       lambda r: vault.update_vault(self.path, r, PASSWORD), lambda _: None)
        self.assertEqual(peer.messages, [b'\1\0', b'\1\1'])
        self.assertEqual(vault.read_vault(self.path, PASSWORD)['phase'], 'prepared')

    async def test_each_lost_reply_preserves_same_keys_without_retry(self):
        for index, step in enumerate((b'\1\0', b'\1\1', b'\1\2', b'\1\3', b'\1\5')):
            with self.subTest(step=step):
                path = self.path.parent / f'case-{index}.qsl1'
                record = copy.deepcopy(self.record)
                vault.create_vault(path, record, PASSWORD)
                peer = SimulatedLock(self, record, path, fail_at=step)
                with self.assertRaises(TimeoutError):
                    await enrollment.handshake(peer, peer.card, record,
                                               lambda r: vault.update_vault(path, r, PASSWORD), lambda _: None)
                self.assertEqual(peer.messages.count(step), 1)
                saved = vault.read_vault(path, PASSWORD)
                for field in ('signing_private_pem', 'mq_private', 'challenge_a', 'phone_uuid'):
                    self.assertEqual(saved[field], self.record[field])
                self.assertNotEqual(saved['state'], 'verified')

    async def test_persist_failure_prevents_public_key_write(self):
        peer = self.peer()
        with self.assertRaises(OSError):
            await enrollment.handshake(peer, peer.card, self.owner,
                                       lambda _: (_ for _ in ()).throw(OSError('disk full')), lambda _: None)
        self.assertEqual(peer.messages, [b'\1\0', b'\1\1'])

    async def test_overall_deadline_bounds_incomplete_notifications(self):
        connection = SimpleNamespace(client=AsyncMock(), queue=asyncio.Queue())
        connection.queue.put_nowait(protocol.frame_message(b'x' * 40)[0])
        with self.assertRaises(TimeoutError):
            await enrollment.exchange(connection, b'\1\0', 0.01)

    async def test_card_and_vault_binding(self):
        enrollment.bind_record(self.owner, ADVERTISEMENT, SERIAL, COEFFICIENTS)
        for ad, serial in ((protocol.LockAdvertisement(None, 'S01-0ABCDEF', bytes(16)), SERIAL),
                           (ADVERTISEMENT, 'S01-1234567-X')):
            with self.assertRaises(ValueError):
                enrollment.bind_record(self.owner, ad, serial, COEFFICIENTS)

    async def test_verify_read_only_then_export_existing_legacy_vault_without_apk(self):
        self.owner['state'] = 'registered'
        vault.write_private(self.path, legacy_blob(self.owner, PASSWORD))
        connection = AsyncMock()
        connection.__aenter__.return_value = connection
        connection.settings.return_value = bytes(7)
        factory = unittest.mock.Mock(return_value=connection)
        result = await enrollment.verify_saved(self.path, PASSWORD, factory=factory)
        self.assertEqual(result['state'], 'verified')
        connection.settings.assert_awaited_once()
        connection.actuate.assert_not_called()
        connection.authenticate.assert_not_called()
        vault.export_owner(result, self.path.parent / 'owner.json')
        self.assertEqual(vault.read_vault(self.path, PASSWORD), result)

    async def test_failed_verify_cannot_export_or_keep_old_verified_marker(self):
        for state in ('verified', 'registered'):
            with self.subTest(state=state):
                path = self.path.parent / (state + '.qsl1')
                self.owner.update(state=state, verification='authenticated-read-status-v1')
                vault.create_vault(path, self.owner, PASSWORD)
                connection = AsyncMock()
                connection.__aenter__.return_value = connection
                connection.settings.side_effect = RuntimeError('synthetic rejected status=132')
                with self.assertRaises(RuntimeError):
                    await enrollment.verify_saved(path, PASSWORD, factory=lambda *a, **k: connection)
                saved = vault.read_vault(path, PASSWORD)
                self.assertEqual(saved['state'], 'acknowledged')
                self.assertNotIn('verification', saved)
                with self.assertRaises(ValueError):
                    vault.export_owner(saved, self.path.parent / 'owner.json')

    async def test_full_workflow_and_explicit_resume_reuse_keys(self):
        # Prepare a partial existing vault; resume must never generate another keypair.
        vault.create_vault(self.path, self.owner, PASSWORD)
        peers = []
        class Connection:
            def __init__(inner, record, **kwargs):
                inner.peer = SimulatedLock(self, record, self.path)
                inner.client, inner.queue = inner.peer, inner.peer.queue
                inner.record = record
                peers.append(inner)
            async def __aenter__(inner): return inner
            async def __aexit__(inner, *args): pass
            async def settings(inner): return bytes(7)
        with patch.object(enrollment, 'prepare_record', side_effect=AssertionError('must reuse saved keys')):
            result = await enrollment.enroll_saved(ADVERTISEMENT, SERIAL, bytes(range(16)), COEFFICIENTS,
                                                   self.path, PASSWORD, resume=True, factory=Connection,
                                                   progress=lambda _: None)
        self.assertEqual(len(peers), 2)
        self.assertEqual(peers[1].peer.messages, [])
        self.assertEqual(result['state'], 'verified')
        self.assertEqual(result['signing_private_pem'], self.record['signing_private_pem'])
        vault.export_owner(result, self.path.parent / 'owner.json')

    async def test_new_enrollment_creates_vault_before_connection(self):
        class FailedConnection:
            def __init__(inner, record, **kwargs):
                self.assertEqual(vault.read_vault(self.path, PASSWORD), record)
                raise RuntimeError('synthetic connection failed')
        with self.assertRaises(RuntimeError):
            await enrollment.enroll_saved(ADVERTISEMENT, SERIAL, bytes(range(16)), COEFFICIENTS,
                                           self.path, PASSWORD, factory=FailedConnection, progress=lambda _: None)
        self.assertEqual(vault.read_vault(self.path, PASSWORD)['state'], 'pending')


class InterfaceTests(unittest.TestCase):
    def test_card_decode_normalization_and_invalid_formats(self):
        self.assertEqual(enrollment.decode_card_code('00000-00000-00000-00000-00000'), bytes(16))
        self.assertEqual(enrollment.normalize_serial(' s01-0abcdef-z '), SERIAL)
        for code in ('I' * 25, 'L' * 25, 'a' * 24, 'a' * 26):
            # I belongs to this historical alphabet; L does not.
            if code == 'I' * 25:
                self.assertEqual(len(enrollment.decode_card_code(code)), 16)
            else:
                with self.assertRaises(ValueError): enrollment.decode_card_code(code)
        with self.assertRaises(ValueError): enrollment.normalize_serial('S02-0ABCDEF-Z')

    def test_cli_requires_off_door_and_hides_getpass_fallback(self):
        with patch('sys.stderr', new_callable=io.StringIO):
            with self.assertRaises(SystemExit):
                parser().parse_args(['enroll', '--apk', 'local.apk', '--vault', 'owner.qsl1'])
        def visible_fallback(_):
            import getpass
            warnings.warn('fallback', getpass.GetPassWarning)
            return 'must not read this'
        with patch('getpass.getpass', side_effect=visible_fallback):
            import getpass
            with self.assertRaises(getpass.GetPassWarning): hidden('test: ')

    def test_cli_does_not_echo_untrusted_exception_secrets(self):
        with patch('onboarding.__main__.run', side_effect=ValueError('SECRET-DO-NOT-PRINT')):
            with patch('sys.stderr', new_callable=io.StringIO) as output:
                self.assertEqual(main(['inspect', '--vault', 'missing.qsl1']), 1)
        self.assertNotIn('SECRET-DO-NOT-PRINT', output.getvalue())
        self.assertIn('ValueError', output.getvalue())


class DiscoveryTests(unittest.IsolatedAsyncioTestCase):
    async def test_relay_discovery_checks_identity_and_always_disconnects(self):
        config = SimpleNamespace(host='192.168.1.123', noise_psk='synthetic', expected_mac='00:11:22:33:44:55')
        data = IDENTITY + bytes.fromhex('00abcdef')
        raw = bytes([len(data) + 3, 0xff, 0x35, 0x02]) + data
        advertisement = SimpleNamespace(data=raw)
        api = AsyncMock()
        api.device_info.return_value = SimpleNamespace(mac_address=config.expected_mac)
        removed = unittest.mock.Mock()
        def subscribe(callback):
            callback(SimpleNamespace(advertisements=[advertisement]))
            return removed
        api.subscribe_bluetooth_le_raw_advertisements = unittest.mock.Mock(side_effect=subscribe)
        with patch('qrio_esphome_transport.RelayConfig.load', return_value=config):
            with patch('aioesphomeapi.APIClient', return_value=api):
                self.assertEqual((await discover(SERIAL, Path('synthetic.json'), seconds=0)).lock_uuid_bytes, IDENTITY)
                removed.assert_called_once()
                api.disconnect.assert_awaited_once()
                api.device_info.return_value = SimpleNamespace(mac_address='00:00:00:00:00:00')
                with self.assertRaises(ValueError):
                    await discover(SERIAL, Path('synthetic.json'), seconds=0)
                self.assertEqual(api.disconnect.await_count, 2)

    async def test_direct_connection_cancellation_disconnects(self):
        import qrio_live
        connection = object.__new__(QrioLive)
        connection.relay_config = None
        connection.relay = connection.client = connection.agent = None
        connection.reset_pairing = False
        connection.lock = SimpleNamespace(device=None)
        connection.find_lock = AsyncMock()
        client = AsyncMock()
        client.is_connected = True
        client.connect.side_effect = asyncio.CancelledError
        with patch.object(qrio_live.sys, 'platform', 'win32'):
            with patch.object(qrio_live, 'BleakClient', return_value=client):
                with self.assertRaises(asyncio.CancelledError):
                    await connection.__aenter__()
        client.disconnect.assert_awaited_once()

    async def test_direct_discovery_collects_ambiguity_and_no_match(self):
        payload = IDENTITY + bytes.fromhex('00abcdef')
        advert = SimpleNamespace(manufacturer_data={0x235: payload}, local_name='Q-SL1', service_uuids=[])
        device = SimpleNamespace(name='Q-SL1')
        data = []
        class Scanner:
            def __init__(inner, detection_callback): inner.callback = detection_callback
            async def __aenter__(inner):
                for value in data: inner.callback(device, value)
                return inner
            async def __aexit__(inner, *args): pass
        with patch('bleak.BleakScanner', Scanner):
            with self.assertRaises(ValueError): await discover(SERIAL, seconds=0)
            data.append(advert)
            self.assertEqual((await discover(SERIAL, seconds=0)).lock_uuid_bytes, IDENTITY)
            data.append(SimpleNamespace(manufacturer_data={0x235: bytes(16) + payload[16:]},
                                        local_name='Q-SL1', service_uuids=[]))
            with self.assertRaises(ValueError): await discover(SERIAL, seconds=0)


if __name__ == '__main__':
    unittest.main()
