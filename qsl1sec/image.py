"""Apply the fixed SEC002 delta to the owner's locally acquired stock image."""

from dataclasses import dataclass
import hashlib
import json
from pathlib import Path
import struct

EEPROM_SIZE = 65536
DS1, DS2, DS_SIZE = 0x580, 0x8000, 26845
STOCK_DS_SHA = '4679b688063dac92d7c326f3e98ba429291bf1140afc2f4b96a1694cb8741c81'
SEC002_SHA = 'ccf6a88bfb1d9b4dd7568bc8abbb386522518435efa564041ecfd29baeec2e82'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def records(data):
    result, cursor = [], 0
    while cursor + 3 <= len(data):
        kind, length = struct.unpack_from('<BH', data, cursor)
        end = cursor + 3 + length
        if end > len(data):
            raise ValueError('Truncated DS record')
        result.append((cursor, kind, length))
        cursor = end
        if kind == 0xFE and length == 0:
            if cursor != len(data):
                raise ValueError('Trailing bytes after DS end')
            return result
        if kind in (0, 0xFF):
            raise ValueError('Unexpected padding before DS end')
    raise ValueError('Missing DS end record')


def apply_delta(stock_ds, spec):
    if len(stock_ds) != spec['bytes'] or digest(stock_ds) != spec['source_sha256']:
        raise ValueError('Unsupported stock DS; no output produced')
    walk = records(stock_ds)
    result, touched = bytearray(stock_ds), set()
    for edit in spec['patches']:
        address, replacement = edit['ram_address'], bytes.fromhex(edit['replacement_hex'])
        locations = []
        for offset, kind, length in walk:
            if kind != 0x0A or length < 4:
                continue
            base = struct.unpack_from('<I', stock_ds, offset + 3)[0]
            if base <= address and address + len(replacement) <= base + length - 4:
                locations.append(offset + 7 + address - base)
        if len(locations) != 1:
            raise ValueError('Patch must resolve to exactly one existing Data record')
        start = locations[0]
        positions = set(range(start, start + len(replacement)))
        if not positions or touched & positions:
            raise ValueError('Empty or overlapping patches')
        if digest(stock_ds[start:start + len(replacement)]) != edit['original_sha256']:
            raise ValueError('Original instruction/data fingerprint differs')
        touched.update(positions)
        result[start:start + len(replacement)] = replacement
    result = bytes(result)
    if len(result) != len(stock_ds) or records(result) != walk or digest(result) != spec['output_sha256']:
        raise ValueError('SEC002 output integrity/record structure check failed')
    return result


def build(stock_ds):
    spec = json.loads((Path(__file__).resolve().parent.parent / 'patches/sec002.json').read_text(encoding='utf-8'))
    if (spec.get('source_sha256') != STOCK_DS_SHA or spec.get('output_sha256') != SEC002_SHA
            or spec.get('bytes') != DS_SIZE or spec.get('version') != 'SEC002'):
        raise ValueError('Unexpected fixed-patch manifest')
    return apply_delta(stock_ds, spec)


def validate_snapshot(eeprom, require_stock_selected=True):
    if len(eeprom) != EEPROM_SIZE or digest(eeprom[DS1:DS1 + DS_SIZE]) != STOCK_DS_SHA:
        raise ValueError('Only the verified 1.4.01 DS1 layout is supported')
    # Validate record structure, not another unit's device-specific SS bytes.
    for offset, kind, size in ((0, 1, 8), (11, 0xFD, 4), (18, 0x40, 6), (27, 2, 10)):
        actual_kind, actual_size = struct.unpack_from('<BH', eeprom, offset)
        if offset == 0 and not require_stock_selected:
            actual_kind = 1
        if (actual_kind, actual_size) != (kind, size):
            raise ValueError('Unsupported SS1 structure')
    if struct.unpack_from('<I', eeprom, 30)[0] != DS1:
        raise ValueError('SS1 does not select the preserved DS1')
    return eeprom[DS1:DS1 + DS_SIZE]


@dataclass
class Plan:
    ss1: bytes
    old_ss2: bytes
    stock_ds: bytes
    candidate: bytes
    new_ss2: bytes


def plan(eeprom):
    stock = validate_snapshot(eeprom)
    secondary = bytearray(eeprom[:40])
    struct.pack_into('<I', secondary, 30, DS2)
    return Plan(eeprom[:40], eeprom[0x100:0x128], stock, build(stock), bytes(secondary))


class WritePolicy:
    def __init__(self, phase, image):
        if phase not in ('stage', 'activate'):
            raise ValueError('Unsupported write phase')
        self.phase, self.image = phase, image
        self.opened = self.ss2_verified = self.recovery = False

    def allows(self, address, data):
        if not self.opened or not data or len(data) > 11:
            return False
        if address == 0x2008AB and data in (b'\x01', b'\xff'):
            return True
        offset = address - 0xFF000000
        if not 0 <= offset < offset + len(data) <= EEPROM_SIZE:
            return False
        if offset // 16 != (offset + len(data) - 1) // 16:
            return False
        if self.phase == 'stage' and DS2 <= offset < offset + len(data) <= DS2 + len(self.image.candidate):
            start = offset - DS2
            return data == self.image.candidate[start:start + len(data)]
        if self.phase == 'activate':
            if 0x100 <= offset < offset + len(data) <= 0x128:
                start = offset - 0x100
                return data == self.image.new_ss2[start:start + len(data)]
            if offset == 0 and len(data) == 1:
                return ((data == b'\0' and self.ss2_verified)
                        or (data == b'\x01' and self.recovery))
        return False
