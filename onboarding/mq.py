"""MQ public-key evaluation; vendor coefficients stay in the user's own APK."""
import hashlib
import io
from pathlib import Path
from . import PrerequisiteError
import secrets
import zipfile

KEY_SIZE = 16
COEFFICIENT_BYTES = 128 * 129 // 2 * KEY_SIZE
LIBRARY_PATH = 'lib/x86_64/libmq.so'
LIBRARY_SHA256 = '725f3cbb447eed0a523d0844f371e657a3cc0c21059274dce520997dc3ad67ff'


def load_coefficients(apk_path):
    """Read a pinned library as data, never install/execute/extract the APK."""
    path = Path(apk_path)
    if not 0 < path.stat().st_size <= 150 * 1024 * 1024:
        raise PrerequisiteError('APK size outside supported bounds')
    with zipfile.ZipFile(path) as archive:
        entries = [entry for entry in archive.infolist() if entry.filename == LIBRARY_PATH]
        if len(entries) != 1 or not 0 < entries[0].file_size <= 4 * 1024 * 1024:
            raise PrerequisiteError('Missing, duplicate or oversized MQ library')
        with archive.open(entries[0]) as source:
            library = source.read(4 * 1024 * 1024 + 1)
    if hashlib.sha256(library).hexdigest() != LIBRARY_SHA256:
        raise PrerequisiteError('Unsupported MQ library fingerprint; no override provided')
    from elftools.elf.elffile import ELFFile
    elf = ELFFile(io.BytesIO(library))
    if elf.elfclass != 64 or not elf.little_endian or elf['e_machine'] != 'EM_X86_64':
        raise PrerequisiteError('Unexpected MQ ELF architecture')
    symbols = elf.get_section_by_name('.dynsym')
    matches = [] if symbols is None else [s for s in symbols.iter_symbols() if s.name == 'MQ_COEF']
    if len(matches) != 1:
        raise PrerequisiteError('Expected exactly one MQ coefficient symbol')
    symbol = matches[0]
    index = symbol['st_shndx']
    if symbol['st_size'] != COEFFICIENT_BYTES or not isinstance(index, int):
        raise PrerequisiteError('Unexpected MQ coefficient symbol')
    section = elf.get_section(index)
    offset = symbol['st_value'] - section['sh_addr']
    if section['sh_type'] == 'SHT_NOBITS' or not 0 <= offset <= section['sh_size'] - COEFFICIENT_BYTES:
        raise PrerequisiteError('MQ coefficients outside the file-backed section')
    result = section.data()[offset:offset + COEFFICIENT_BYTES]
    if len(result) != COEFFICIENT_BYTES:
        raise PrerequisiteError('Truncated MQ coefficients')
    return result


def public_from_private(private_key, coefficients):
    """Evaluate the quadratic map with the native table's word ordering."""
    if len(private_key) != KEY_SIZE or len(coefficients) != COEFFICIENT_BYTES:
        raise PrerequisiteError('Unexpected MQ key or coefficient size')
    words = [int.from_bytes(private_key[start:start + 4], 'big') for start in range(0, 16, 4)]
    selected = [bit for bit in range(128) if words[bit // 32] & (1 << (bit % 32))]
    result = bytearray(16)
    for index, high in enumerate(selected):
        row = high * (high + 1) // 2
        for low in selected[:index + 1]:
            start = (row + low) * 16
            for byte in range(16):
                result[byte] ^= coefficients[start + byte]
    return b''.join(result[start:start + 4][::-1] for start in range(0, 16, 4))


def generate_keypair(coefficients):
    private = secrets.token_bytes(16)
    return private, public_from_private(private, coefficients)
