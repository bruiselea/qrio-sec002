"""Scoped Linux BLE connection and fixed, bounded FWU primitives.

No erase/launch support. Writes require the fixed SEC002 address/data policy.
"""

import asyncio
from contextlib import asynccontextmanager
import json
import re
import socket
import struct
import sys
import time

SERVICE = '466ab9a5-8129-5b97-5841-69c124fba0df'
MODEL = '00002a24-0000-1000-8000-00805f9b34fb'
REVISION = '00002a26-0000-1000-8000-00805f9b34fb'
BASE, CID = 0xFF000000, 0xFA


def linux_only():
    if sys.platform != 'linux':
        raise RuntimeError('Wireless transport requires Linux/BlueZ; Windows Web Bluetooth cannot send this raw CID')


def address(value):
    if not re.fullmatch(r'(?:[0-9a-fA-F]{2}:){5}[0-9a-fA-F]{2}', value):
        raise ValueError('Use one explicit Bluetooth address from scan')
    return value.upper()


def identity(device, adv):
    payload = bytes(adv.manufacturer_data.get(0x0235, b''))
    name = adv.local_name or device.name
    if len(payload) >= 20 and (name == 'Q-SL1' or SERVICE in adv.service_uuids):
        return payload[:16].hex()
    return None


async def scan(seconds=10, adapter='hci0'):
    linux_only()
    from bleak import BleakScanner
    result = await BleakScanner.discover(timeout=seconds, adapter=adapter, return_adv=True)
    return [{'address': device.address, 'name': 'Q-SL1', 'rssi': adv.rssi}
            for device, adv in result.values() if identity(device, adv)]


async def find(peer, expected, adapter, seconds=25):
    from bleak import BleakScanner
    selected = {}

    def wanted(device, adv):
        value = identity(device, adv)
        if device.address.upper() == peer and value and (expected is None or value == expected):
            selected.update(device=device, identity=value)
            return True
        return False

    await BleakScanner.find_device_by_filter(wanted, timeout=seconds, adapter=adapter)
    if not selected:
        raise RuntimeError('Selected Q-SL1 identity was not found; no write sent')
    return selected


def make_agent(peer_path):
    from dbus_fast import DBusError
    from dbus_fast.service import ServiceInterface, method

    class Agent(ServiceInterface):
        def __init__(self):
            super().__init__('org.bluez.Agent1')

        def check(self, path):
            if path != peer_path:
                raise DBusError('org.bluez.Error.Rejected', 'Only the selected Q-SL1 is permitted')

        @method()
        def Release(self):
            pass

        @method()
        def Cancel(self):
            pass

        @method()
        def RequestPinCode(self, device: 'o') -> 's':
            raise DBusError('org.bluez.Error.Rejected', 'Unexpected PIN request')

        @method()
        def RequestPasskey(self, device: 'o') -> 'u':
            raise DBusError('org.bluez.Error.Rejected', 'Unexpected passkey request')

        @method()
        def RequestConfirmation(self, device: 'o', passkey: 'u'):
            self.check(device)

        @method()
        def RequestAuthorization(self, device: 'o'):
            self.check(device)

        @method()
        def AuthorizeService(self, device: 'o', service_uuid: 's'):
            self.check(device)

    return Agent()


@asynccontextmanager
async def connect(peer, expected=None, adapter='hci0'):
    linux_only()
    from bleak import BleakClient
    from dbus_fast import BusType
    from dbus_fast.aio import MessageBus
    peer = address(peer)
    selected = await find(peer, expected, adapter)
    await BleakClient(selected['device']).unpair()
    selected = await find(peer, selected['identity'], adapter)
    bus, manager, client = None, None, None
    agent_path = '/qsl1sec/agent'
    try:
        bus = await MessageBus(bus_type=BusType.SYSTEM).connect()
        bus.export(agent_path, make_agent(selected['device'].details['path']))
        info = await bus.introspect('org.bluez', '/org/bluez')
        manager = bus.get_proxy_object('org.bluez', '/org/bluez', info).get_interface('org.bluez.AgentManager1')
        await manager.call_register_agent(agent_path, 'NoInputNoOutput')
        await manager.call_request_default_agent(agent_path)
        client = BleakClient(selected['device'], pair=True, timeout=30)
        await client.connect()
        model = bytes(await client.read_gatt_char(MODEL)).rstrip(b'\0')
        revision = bytes(await client.read_gatt_char(REVISION)).rstrip(b'\0').decode('ascii')
        if model != b'Q-SL1':
            raise RuntimeError('Selected device model mismatch')
        yield client, selected['identity'], revision
    finally:
        if client is not None and client.is_connected:
            try:
                await client.disconnect()
            except Exception:
                pass
        if manager is not None:
            try:
                await manager.call_unregister_agent(agent_path)
            except Exception:
                pass
        if bus is not None:
            bus.disconnect()


def checksum(data):
    return -sum(data) & 255


def readable16(location):
    return (location % 16 == 0 and (BASE <= location <= BASE + 65536 - 16 or
            location in (0, 0x17470, 0x17480, 0x2008A0, 0x2008B0, 0x2008C0, 0x200DA0, 0x2044D0)))


def acl(handle, payload):
    if not 0 <= handle <= 0xEFF or not 1 <= len(payload) <= 19:
        raise ValueError('Invalid scoped ACL frame')
    frame = struct.pack('<HH', len(payload), CID) + payload
    return b'\x02' + struct.pack('<HH', handle, len(frame)) + frame


class Reassembler:
    def __init__(self, handle):
        self.handle, self.pending, self.expected = handle, None, 0

    def feed(self, frame):
        if len(frame) < 5 or frame[0] != 2:
            return None
        flags, size = struct.unpack_from('<HH', frame, 1)
        if flags & 4095 != self.handle or size != len(frame) - 5:
            return None
        boundary, data = (flags >> 12) & 3, frame[5:]
        if boundary in (0, 2):
            self.pending = None
            if len(data) < 4:
                return None
            length, cid = struct.unpack_from('<HH', data)
            if cid != CID or length > 512:
                return None
            self.expected, self.pending = length, bytearray(data[4:])
        elif boundary == 1 and self.pending is not None:
            self.pending.extend(data)
        if self.pending is not None and len(self.pending) == self.expected:
            result, self.pending = bytes(self.pending), None
            return result
        if self.pending is not None and len(self.pending) > self.expected:
            self.pending = None
        return None


def read_report(payload, expected):
    value = b'\x72' + payload if len(payload) == 23 else payload
    if len(value) != 24 or value[0] != 0x72 or sum(value) & 255:
        return None
    address_value, length = struct.unpack_from('<IH', value, 1)
    return value[7:-1] if address_value == expected and length == 16 else None


class Session:
    def __init__(self, peer, adapter='hci0', policy=None):
        linux_only()
        import fcntl
        if not re.fullmatch(r'hci[0-9]{1,2}', adapter):
            raise ValueError('Expected hci0, hci1, ...')
        self.policy, self.write_attempts = policy, 0
        self.peer, self.adapter = address(peer), adapter
        self.sock = socket.socket(socket.AF_BLUETOOTH, socket.SOCK_RAW, socket.BTPROTO_HCI)
        try:
            index = int(adapter[3:])
            self.sock.bind((index,))
            self.sock.setsockopt(0, 2, struct.pack('<IIIH2x', 1 << 2, 0, 0, 0))
            self.sock.setsockopt(0, 1, struct.pack('i', 1))
            self.sock.settimeout(0.2)
            item_size = struct.calcsize('<H6sBBHI')
            table = bytearray(struct.pack('<HH', index, 32) + bytes(32 * item_size))
            fcntl.ioctl(self.sock.fileno(), 0x800448D4, table, True)
            target = bytes.fromhex(address(peer).replace(':', ''))[::-1]
            handles = []
            for i in range(min(struct.unpack_from('<H', table, 2)[0], 32)):
                handle, mac, kind, _, _, _ = struct.unpack_from('<H6sBBHI', table, 4 + i * item_size)
                if mac == target and kind == 0x80:
                    handles.append(handle)
            if len(handles) != 1:
                raise RuntimeError('Expected exactly one LE handle for the selected Q-SL1')
            self.handle, self.assembler = handles[0], Reassembler(handles[0])
        except BaseException:
            self.sock.close()
            raise

    def close(self):
        self.sock.close()

    def send(self, payload):
        # A stale LE handle must never be reused after a disconnect.
        import fcntl
        index, item_size = int(self.adapter[3:]), struct.calcsize('<H6sBBHI')
        table = bytearray(struct.pack('<HH', index, 32) + bytes(32 * item_size))
        fcntl.ioctl(self.sock.fileno(), 0x800448D4, table, True)
        target = bytes.fromhex(self.peer.replace(':', ''))[::-1]
        found = False
        for i in range(min(struct.unpack_from('<H', table, 2)[0], 32)):
            handle, mac, kind, _, _, _ = struct.unpack_from('<H6sBBHI', table, 4 + i * item_size)
            found |= handle == self.handle and mac == target and kind == 0x80
        if not found:
            raise RuntimeError('Selected LE handle no longer belongs to this peer; no packet sent')
        frame = acl(self.handle, payload)
        if self.sock.send(frame) != len(frame):
            raise RuntimeError('Short HCI send; not retried')

    async def next_reply(self, predicate):
        # Do not leave a cancelled receive thread competing with WP cleanup.
        pending = asyncio.create_task(asyncio.to_thread(self.receive, predicate))
        try:
            return await asyncio.shield(pending)
        except asyncio.CancelledError:
            try:
                await pending
            except Exception:
                pass
            raise

    def receive(self, predicate, seconds=3):
        deadline = time.monotonic() + seconds
        while time.monotonic() < deadline:
            try:
                frame, ancillary, _, _ = self.sock.recvmsg(4096, 128)
            except socket.timeout:
                continue
            incoming = any(level == 0 and kind == 1 and len(data) >= 4 and struct.unpack('i', data[:4])[0] == 1
                           for level, kind, data in ancillary)
            if incoming:
                result = self.assembler.feed(frame)
                if result is not None and predicate(result):
                    return result
        raise TimeoutError('No matching reply; request was not automatically retried')

    async def command(self, payload):
        if payload == b'\x70':
            permitted = self.policy is not None and self.policy.opened
        elif len(payload) == 8 and payload[0] == 0x71:
            location, size = struct.unpack_from('<IH', payload, 1)
            permitted = size == 16 and readable16(location) and not (sum(payload) & 255)
        elif 9 <= len(payload) <= 19 and payload[0] == 0x74:
            location, size = struct.unpack_from('<IH', payload, 1)
            data = payload[7:-1]
            permitted = (size == len(data) and not (sum(payload) & 255)
                         and self.policy is not None and self.policy.allows(location, data))
        else:
            permitted = False
        if not permitted:
            raise ValueError('Only bounded read, fixed-policy enable and fixed-policy write are supported')
        self.send(payload)
        result = await self.next_reply(lambda r: len(r) == 1)
        if result != b'\0':
            raise RuntimeError(f'FWU command rejected with status {result[0]}')

    async def read16(self, location):
        if not readable16(location):
            raise ValueError('Read outside fixed EEPROM/runtime/fingerprint regions')
        setup = b'\x71' + struct.pack('<IH', location, 16)
        await self.command(setup + bytes([checksum(setup)]))
        self.send(b'\x72\x8e')
        result = await self.next_reply(lambda r: read_report(r, location) is not None)
        return read_report(result, location)

    async def read(self, offset, size, progress=None):
        if not 0 <= offset < offset + size <= 65536:
            raise ValueError('Read escaped EEPROM')
        low, high = offset & ~15, (offset + size + 15) & ~15
        setup = b'\x71' + struct.pack('<IH', BASE + low, 16)
        await self.command(setup + bytes([checksum(setup)]))
        output = bytearray()
        for page in range(low, high, 16):
            self.send(b'\x72\x8e')
            result = await self.next_reply(lambda r: read_report(r, BASE + page) is not None)
            output.extend(read_report(result, BASE + page))
            if progress:
                progress(min(page + 16 - offset, size), size)
        return bytes(output[offset - low:offset - low + size])

    async def write(self, location, data):
        if self.policy is None or not self.policy.allows(location, data):
            raise ValueError('Write refused by fixed SEC002 address/data policy')
        payload = b'\x74' + struct.pack('<IH', location, len(data)) + data
        self.write_attempts += 1
        await self.command(payload + bytes([checksum(payload)]))
