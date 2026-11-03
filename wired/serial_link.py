"""Binary USB/UART link and bounded HCI requests; no reset, erase or loader."""
import random
import struct
import time

from . import RecoveryError

EEPROM_BASE, EEPROM_SIZE = 0xFF000000, 65536
WP_PIN, WP_CONFIG, WP_CALLBACK = 0x2008AB, 0x200DA4, 0x200DA8
ROM_CALLBACK = (0x16D51).to_bytes(4, 'little')
ROM_REGIONS = ((0x16D50, 108), (0x2F2D4, 160))
ROM_FINGERPRINTS = ('287ebdc17c3ad885e188b7d7a4974b9c252855447d9b3e01a5144c7b33e4cdde',
                    '47a1a2bea3a1f8b95ea7af50b481c447adf0de8b3302c3dde41f6166ed4a9044')
VERSION = (7, 4096, 7, 15, 0x220F)


def ports():
    from serial.tools import list_ports
    # Do not print USB serial numbers, hardware IDs or device descriptions.
    return [{'port': item.device, 'vid': item.vid, 'pid': item.pid,
             'c3_native_usb': (item.vid, item.pid) == (0x303A, 0x1001)}
            for item in list_ports.comports()]


def open_port(name, adapter='c3'):
    import os
    import serial
    from serial.tools import list_ports
    matches = [item for item in list_ports.comports() if item.device.casefold() == name.casefold()]
    if len(matches) != 1:
        raise RecoveryError('Expected one explicit enumerated USB serial port')
    item = matches[0]
    if adapter == 'c3':
        if (item.vid, item.pid) != (0x303A, 0x1001):
            raise RecoveryError('C3 native USB port 303A:1001 required')
    elif adapter == 'uart-3v3':
        if item.vid is None or item.pid is None:
            raise RecoveryError('Expected a USB UART adapter; verify 3.3V logic physically')
    else:
        raise RecoveryError('Unsupported adapter selection')
    connection = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=3,
                               bytesize=8, parity='N', stopbits=1,
                               xonxoff=False, rtscts=False, dsrdtr=False,
                               exclusive=True if os.name == 'posix' else None)
    connection.dtr = adapter == 'c3'
    connection.rts = False
    connection.port = item.device
    try:
        connection.open()
    except BaseException:
        connection.close()
        raise
    return connection


def drain_until_quiet(connection, quiet_seconds=0.15, seconds=2, maximum=32768):
    start = last = time.monotonic()
    count = 0
    while time.monotonic() - start < seconds and count < maximum:
        data = connection.read(min(512, maximum - count))
        if data:
            count += len(data)
            last = time.monotonic()
        elif time.monotonic() - last >= quiet_seconds:
            return
    raise RecoveryError('UART did not become quiet; no request sent')


class EventParser:
    def __init__(self):
        self.buffer = bytearray()
        self.events = []

    def feed(self, data):
        self.buffer.extend(data)
        if len(self.buffer) > 2048:
            raise RecoveryError('UART event buffer exceeded its bound')
        while self.buffer:
            if self.buffer[0] != 4:
                raise RecoveryError('Unexpected UART bytes; check bridge and wiring')
            if len(self.buffer) < 3 or len(self.buffer) < 3 + self.buffer[2]:
                return
            end = 3 + self.buffer[2]
            self.events.append((self.buffer[1], bytes(self.buffer[3:end])))
            del self.buffer[:end]


class HCI:
    def __init__(self, connection, allow_writes=False):
        self.connection = connection
        self.allow_writes = allow_writes

    def _request(self, opcode, payload=b'', result_length=0):
        if opcode not in (0x1001, 0xFC4D, 0xFC4C) or len(payload) > 255:
            raise RecoveryError('Unsupported HCI command')
        if opcode == 0xFC4C and not self.allow_writes:
            raise RecoveryError('This connection is read-only')
        if opcode == 0xFC4C:
            allowed = (struct.pack('<I', WP_PIN) + b'\1', struct.pack('<I', WP_PIN) + b'\xff',
                       struct.pack('<I', WP_CALLBACK) + ROM_CALLBACK,
                       struct.pack('<I', WP_CALLBACK) + bytes(4),
                       struct.pack('<I', EEPROM_BASE) + b'\1')
            if payload not in allowed or result_length:
                raise RecoveryError('Only fixed WP values and the one-byte stock selector may be written')
        frame = b'\1' + struct.pack('<HB', opcode, len(payload)) + payload
        if self.connection.write(frame) != len(frame):
            raise RecoveryError('Short UART command; no retry; result may be unknown')
        parser = EventParser()
        received = bytearray()
        deadline = time.monotonic() + 4
        while time.monotonic() < deadline and len(received) < 1024:
            data = self.connection.read(min(256, 1024 - len(received)))
            received.extend(data)
            parser.feed(data)
            for event, parameters in parser.events:
                if event == 0x0E and len(parameters) >= 4 and int.from_bytes(parameters[1:3], 'little') == opcode:
                    if parameters[3] or len(parameters) != 4 + result_length:
                        raise RecoveryError('HCI rejected request or returned wrong length; no retry')
                    return parameters[4:]
                if event == 0x0F and len(parameters) == 4 and int.from_bytes(parameters[2:], 'little') == opcode and parameters[0]:
                    raise RecoveryError('HCI command status rejected; no retry')
            parser.events.clear()
        raise RecoveryError('UART response deadline/limit reached; no retry; result may be unknown')

    def version(self):
        return struct.unpack('<BHBHH', self._request(0x1001, result_length=8))

    def require_version(self):
        if self.version() != VERSION:
            raise RecoveryError('Unsupported HCI version; no write sent')

    def read_memory(self, address, length):
        if type(address) is not int or type(length) is not int or not 1 <= length <= 64:
            raise RecoveryError('Read outside supported bounds')
        ranges = ((EEPROM_BASE, EEPROM_SIZE), *ROM_REGIONS, (WP_PIN, 1), (WP_CONFIG, 8))
        if not any(base <= address and address + length <= base + size for base, size in ranges):
            raise RecoveryError('Read outside EEPROM and fixed ROM/runtime fields')
        return self._request(0xFC4D, struct.pack('<IB', address, length), length)

    def read_region(self, address, length):
        return b''.join(self.read_memory(address + offset, min(64, length - offset))
                        for offset in range(0, length, 64))

    def read_eeprom(self, progress=None):
        result = bytearray()
        for offset in range(0, EEPROM_SIZE, 64):
            result.extend(self.read_memory(EEPROM_BASE + offset, 64))
            if progress is not None and len(result) % 8192 == 0:
                progress(len(result), EEPROM_SIZE)
        return bytes(result)

    def write_runtime(self, address, data):
        permitted = ((address == WP_PIN and data in (b'\1', b'\xff'))
                     or (address == WP_CALLBACK and data in (ROM_CALLBACK, bytes(4))))
        if not permitted:
            raise RecoveryError('Runtime write is outside the fixed WP settings')
        self._request(0xFC4C, struct.pack('<I', address) + data)
        if self.read_memory(address, len(data)) != data:
            raise RecoveryError('Runtime WP setting failed readback')

    def write_stock_marker(self):
        # No API for DS, arbitrary EEPROM bytes, erases or executable loaders.
        if self.read_memory(WP_PIN, 1) != b'\1' or self.read_memory(WP_CALLBACK, 4) != ROM_CALLBACK:
            raise RecoveryError('Verified ROM WP settings are not enabled')
        self._request(0xFC4C, struct.pack('<I', EEPROM_BASE) + b'\1')
        time.sleep(0.006)
        if self.read_memory(EEPROM_BASE, 16)[:1] != b'\1':
            raise RecoveryError('Marker ACK did not produce the expected EEPROM byte')


def loopback(connection, size=65536, timeout=4):
    if size not in (256, 4096, 65536):
        raise RecoveryError('Unsupported loopback size')
    payload = (bytes(range(256)) + random.Random(0xC300051).randbytes(size))[:size]
    connection.reset_input_buffer()
    for offset in range(0, size, 256):
        chunk = payload[offset:offset + 256]
        if connection.write(chunk) != len(chunk):
            raise RecoveryError('Short loopback write; no retry')
        received = bytearray()
        deadline = time.monotonic() + timeout
        while len(received) < len(chunk) and time.monotonic() < deadline:
            received.extend(connection.read(len(chunk) - len(received)))
        if bytes(received) != chunk:
            raise RecoveryError('Loopback mismatch/timeout; no retry')
    if connection.read(1):
        raise RecoveryError('Unexpected trailing loopback bytes')
    return {'loopback_bytes_verified': size}
