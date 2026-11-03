"""Synthetic offline tests: no Bluetooth, vendor firmware or real credentials."""

import asyncio
import base64
import copy
import json
from pathlib import Path
import struct
import sys
import tempfile
import threading
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from qsl1sec import private
from qsl1sec.image import Plan, WritePolicy, apply_delta, digest, records, DS1, DS2
from qsl1sec.install import stage_image, activate_image, recover_selector, enable, restore_wp
from qsl1sec.radio import Session, Reassembler, acl, checksum, read_report, readable16


def fixture():
    first = bytearray(40)
    for position, kind, size in ((0, 1, 8), (11, 0xFD, 4), (18, 0x40, 6), (27, 2, 10)):
        struct.pack_into('<BH', first, position, kind, size)
    struct.pack_into('<I', first, 30, DS1)
    second = bytearray(first)
    struct.pack_into('<I', second, 30, DS2)
    eeprom = bytearray(b'\xff' * 65536)
    eeprom[:40] = first
    candidate = bytes(range(61))
    eeprom[DS1:DS1 + 64] = b'STOCK' * 12 + b'SAFE'
    return bytes(eeprom), Plan(bytes(first), bytes(eeprom[0x100:0x128]), bytes(eeprom[DS1:DS1 + 64]), candidate, bytes(second))


class FakeSession:
    def __init__(self, data, policy, fail=None, apply_before_failure=False):
        self.data, self.policy = bytearray(data), policy
        self.fail, self.apply_before_failure = fail, apply_before_failure
        self.writes = []

    async def read(self, offset, size, progress=None):
        return bytes(self.data[offset:offset + size])

    async def write(self, location, data):
        if not self.policy.allows(location, data):
            raise ValueError('Policy denied write before transport')
        self.writes.append((location, bytes(data)))
        failing = len(self.writes) - 1 == self.fail
        if not failing or self.apply_before_failure:
            start = location - 0xFF000000
            self.data[start:start + len(data)] = data
        if failing:
            raise TimeoutError('Synthetic lost reply; not retried')


class ImageTests(unittest.TestCase):
    def test_delta_preserves_record_layout(self):
        source = struct.pack('<BHI', 0x0A, 20, 0x200000) + bytes(16) + b'\xb9\x03\0abc\xfe\0\0'
        changed = bytearray(source)
        changed[11:13] = b'OK'
        spec = {'bytes': len(source), 'source_sha256': digest(source), 'output_sha256': digest(changed),
                'patches': [{'ram_address': 0x200004, 'original_sha256': digest(b'\0\0'), 'replacement_hex': '4f4b'}]}
        self.assertEqual(apply_delta(source, spec), bytes(changed))
        self.assertEqual(records(source), records(changed))
        for address in (0x1FFFFF, 0x200010):
            altered = copy.deepcopy(spec)
            altered['patches'][0]['ram_address'] = address
            with self.assertRaises(ValueError):
                apply_delta(source, altered)
        altered = copy.deepcopy(spec)
        altered['patches'] *= 2
        with self.assertRaises(ValueError):
            apply_delta(source, altered)
        with self.assertRaises(ValueError):
            records(source[:-1])

    def test_policy_rejects_all_non_target_regions(self):
        _, image = fixture()
        for phase in ('stage', 'activate'):
            policy = WritePolicy(phase, image)
            self.assertFalse(policy.allows(0x2008AB, b'\x01'))
            policy.opened = True
            for offset in (1, 0x80, 0x280, DS1, 0x6E5C, 0x7FFF, 0xFFFF):
                self.assertFalse(policy.allows(0xFF000000 + offset, b'X'))
            self.assertFalse(policy.allows(0xFF00800F, image.candidate[15:17]))
            self.assertFalse(policy.allows(0xFF008000, b'X' * 12))
        policy = WritePolicy('activate', image)
        policy.opened = True
        self.assertFalse(policy.allows(0xFF000000, b'\0'))
        policy.ss2_verified = True
        self.assertTrue(policy.allows(0xFF000000, b'\0'))


class PrivateTests(unittest.TestCase):
    def test_portable_authenticated_backup(self):
        password = 'synthetic-passphrase'
        payload = {'kind': 'synthetic', 'data': 'synthetic-private-content'}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / 'test.qsb'
            private.save(path, payload, password)
            self.assertEqual(private.load(path, password), payload)
            self.assertNotIn(payload['data'].encode(), path.read_bytes())
            with self.assertRaises(FileExistsError):
                private.save(path, payload, password)
            with self.assertRaises(ValueError):
                private.load(path, 'different-passphrase')
            record = private.seal(payload, password)
            record['created_utc'] = 'modified'
            with self.assertRaises(ValueError):
                private.open_envelope(record, password)
            with self.assertRaises(ValueError):
                private.seal(payload, 'short')


class TransportTests(unittest.IsolatedAsyncioTestCase):
    async def test_stale_or_reassigned_handle_refused_before_send(self):
        session = object.__new__(Session)
        session.peer, session.adapter, session.handle = '00:11:22:33:44:55', 'hci0', 7
        sent = []
        session.sock = SimpleNamespace(fileno=lambda: 5, send=lambda data: sent.append(data) or len(data))
        rows = []

        def ioctl(fd, opcode, buffer, mutate):
            self.assertEqual(opcode, 0x800448D4)
            struct.pack_into('<H', buffer, 2, len(rows))
            for i, (handle, peer, kind) in enumerate(rows):
                struct.pack_into('<H6sBBHI', buffer, 4 + i * 16, handle,
                                 bytes.fromhex(peer.replace(':', ''))[::-1], kind, 0, 0, 0)
        with patch.dict(sys.modules, {'fcntl': SimpleNamespace(ioctl=ioctl)}):
            for row in (None, (7, '00:11:22:33:44:66', 0x80),
                        (8, session.peer, 0x80), (7, session.peer, 1)):
                rows[:] = [] if row is None else [row]
                with self.assertRaises(RuntimeError):
                    session.send(b'\x72\x8e')
                self.assertEqual(sent, [])
            rows[:] = [(7, session.peer, 0x80)]
            session.send(b'\x72\x8e')
            self.assertEqual(len(sent), 1)

    async def test_unsafe_commands_rejected_before_send(self):
        session = object.__new__(Session)
        session.policy = None
        sent = []
        session.send = sent.append

        async def reply(predicate):
            return b'\0'
        session.next_reply = reply
        for packet in (b'\x70', b'\x73' + bytes(8), b'\x75' + bytes(8), b'\x74' + bytes(8)):
            with self.assertRaises(ValueError):
                await session.command(packet)
        self.assertEqual(sent, [])
        setup = b'\x71' + struct.pack('<IH', 0, 16)
        await session.command(setup + bytes([checksum(setup)]))
        self.assertEqual(len(sent), 1)

    async def test_cancel_waits_for_receiver_to_finish(self):
        session = object.__new__(Session)
        entered, finished = threading.Event(), threading.Event()
        release = threading.Event()

        def receive(predicate):
            entered.set()
            release.wait(0.5)
            finished.set()
            return b'\0'
        session.receive = receive
        task = asyncio.create_task(session.next_reply(lambda _: True))
        await asyncio.to_thread(entered.wait, 0.2)
        task.cancel()
        await asyncio.sleep(0.01)
        self.assertFalse(task.done())
        release.set()
        with self.assertRaises(asyncio.CancelledError):
            await task
        self.assertTrue(finished.is_set())

    async def test_acl_and_read_report(self):
        peer = 7
        response = struct.pack('<IH', 0xFF000000, 16) + bytes(16)
        response += bytes([checksum(b'\x72' + response)])
        self.assertEqual(read_report(response, 0xFF000000), bytes(16))
        self.assertIsNone(read_report(response, 0xFF000010))
        self.assertIsNone(read_report(response[:-1] + b'\0', 0xFF000000))
        assembler = Reassembler(peer)
        # Incoming read report is longer than the bounded outgoing probe size.
        packet = struct.pack('<HH', len(response), 0xFA) + response
        first, rest = packet[:12], packet[12:]
        self.assertIsNone(assembler.feed(b'\x02' + struct.pack('<HH', peer, len(first)) + first))
        self.assertEqual(assembler.feed(b'\x02' + struct.pack('<HH', peer | 0x1000, len(rest)) + rest), response)
        self.assertIsNone(Reassembler(peer + 1).feed(acl(peer, b'\0')))
        for location in (0xFFFFFFFF, 0x200000, 0xFF010000, 1):
            self.assertFalse(readable16(location))


class TransactionTests(unittest.IsolatedAsyncioTestCase):
    async def test_runtime_mismatch_stops_before_enable_or_write(self):
        config, timer, driver, utility = (bytearray(16) for _ in range(4))
        config[:8] = bytes.fromhex('70 71 72 73 74 75 fa 00')
        struct.pack_into('<H', timer, 0, 10)
        struct.pack_into('<i', timer, 4, -1)
        driver[4] = 16
        struct.pack_into('<I', driver, 8, 0x16D51)
        utility[11] = 255
        known = {0x2008B0: config, 0x2008C0: timer, 0x200DA0: driver,
                 0x2008A0: utility, 0x17470: bytearray(16), 0x17480: bytearray(16)}
        fake_spec = json.dumps({'rom_fwu_fingerprint_sha256': digest(bytes(32))})

        class Runtime:
            def __init__(self):
                self.memory = copy.deepcopy(known)
                self.policy = SimpleNamespace(opened=False)
                self.commands, self.writes = [], []

            async def read16(self, address):
                return bytes(self.memory[address])

            async def command(self, value):
                self.commands.append(value)

            async def write(self, address, value):
                self.writes.append((address, value))
                self.memory[0x2008A0][11] = value[0]

        with patch('qsl1sec.install.Path.read_text', return_value=fake_spec):
            for address, position, value in ((0x2008B0, 0, 0), (0x2008B0, 14, 1),
                                             (0x2008C0, 0, 11), (0x2008C0, 4, 0),
                                             (0x200DA0, 4, 32), (0x200DA0, 8, 0),
                                             (0x2008A0, 11, 1), (0x17470, 0, 1)):
                session = Runtime()
                session.memory[address][position] = value
                with self.assertRaises(RuntimeError):
                    await enable(session)
                self.assertFalse(session.policy.opened)
                self.assertEqual(session.commands, [])
                self.assertEqual(session.writes, [])
            session = Runtime()
            await enable(session)
            self.assertEqual(session.writes, [(0x2008AB, b'\x01')])
            await restore_wp(session)
            self.assertEqual(session.memory[0x2008A0][11], 255)
            self.assertEqual(session.writes[-1], (0x2008AB, b'\xff'))

    async def test_stage_preserves_tail_selectors_and_owner_storage(self):
        before, image = fixture()
        policy = WritePolicy('stage', image)
        policy.opened = True
        session = FakeSession(before, policy)
        after = await stage_image(session, image, before)
        self.assertEqual(after[:DS2], before[:DS2])
        self.assertEqual(after[DS2 + len(image.candidate):], before[DS2 + len(image.candidate):])
        for location, data in session.writes:
            offset = location - 0xFF000000
            self.assertLessEqual(len(data), 11)
            self.assertEqual(offset // 16, (offset + len(data) - 1) // 16)

    async def test_activation_failure_at_every_write_and_lost_ack(self):
        original, image = fixture()
        before = bytearray(original)
        before[DS2:DS2 + len(image.candidate)] = image.candidate
        success_policy = WritePolicy('activate', image)
        success_policy.opened = True
        success = FakeSession(before, success_policy)
        await activate_image(success, image)
        self.assertEqual(success.data[0], 0)
        for cut in range(len(success.writes)):
            for applied in (False, True):
                policy = WritePolicy('activate', image)
                policy.opened = True
                session = FakeSession(before, policy, cut, applied)
                with self.assertRaises(TimeoutError):
                    await activate_image(session, image)
                self.assertEqual(len(session.writes), cut + 1)
                stock_valid = session.data[:40] == image.ss1
                new_valid = session.data[0x100:0x128] == image.new_ss2
                self.assertTrue(stock_valid or new_valid)
                self.assertEqual(session.data[DS1:DS1 + 64], image.stock_ds)
                # Link-alive selector recovery is a different one-byte write,
                # not a retry of a lost activation acknowledgement.
                session.fail = None
                session.command = lambda _: asyncio.sleep(0)
                async def runtime_write(location, data):
                    if location == 0x2008AB:
                        return
                    await FakeSession.write(session, location, data)
                session.write = runtime_write
                self.assertTrue(await recover_selector(session, image))
                self.assertEqual(session.data[:40], image.ss1)

    async def test_unverified_candidate_cannot_activate(self):
        before, image = fixture()
        policy = WritePolicy('activate', image)
        policy.opened = True
        session = FakeSession(before, policy)
        with self.assertRaises(RuntimeError):
            await activate_image(session, image)
        self.assertEqual(session.writes, [])


if __name__ == '__main__':
    unittest.main()
