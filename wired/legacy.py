"""Offline import of an owner's old Windows DPAPI EEPROM backup."""
import base64
import ctypes
from ctypes import wintypes
import hashlib
import json
from pathlib import Path
import sys

from . import RecoveryError


def unprotect(data):
    if sys.platform != 'win32':
        raise RecoveryError('DPAPI import requires the original Windows account and machine')
    class Blob(ctypes.Structure):
        _fields_ = [('size', wintypes.DWORD), ('data', ctypes.POINTER(ctypes.c_ubyte))]
    crypt = ctypes.WinDLL('crypt32', use_last_error=True)
    kernel = ctypes.WinDLL('kernel32', use_last_error=True)
    backing = ctypes.create_string_buffer(data)
    source = Blob(len(data), ctypes.cast(backing, ctypes.POINTER(ctypes.c_ubyte)))
    output = Blob()
    crypt.CryptUnprotectData.argtypes = [ctypes.POINTER(Blob), ctypes.c_void_p, ctypes.c_void_p,
                                         ctypes.c_void_p, ctypes.c_void_p, wintypes.DWORD, ctypes.POINTER(Blob)]
    crypt.CryptUnprotectData.restype = wintypes.BOOL
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    kernel.LocalFree.restype = ctypes.c_void_p
    if not crypt.CryptUnprotectData(ctypes.byref(source), None, None, None, None, 1, ctypes.byref(output)):
        raise RecoveryError('Windows could not decrypt this DPAPI backup')
    try:
        if output.size != 65536:
            raise RecoveryError('Only full 64 KiB DPAPI EEPROM backups are supported')
        return ctypes.string_at(output.data, output.size)
    finally:
        ctypes.memset(output.data, 0, output.size)
        kernel.LocalFree(output.data)


def read_legacy(path):
    with Path(path).open('rb') as source:
        encoded = source.read(250001)
    if len(encoded) > 250000:
        raise RecoveryError('DPAPI envelope exceeds its bound')
    record = json.loads(encoded)
    if record.get('format') != 'qrio-sl1-firmware-dpapi-v1' or record.get('bytes') != 65536:
        raise RecoveryError('Unsupported legacy EEPROM backup')
    data = unprotect(base64.b64decode(record['protected'], validate=True))
    if hashlib.sha256(data).hexdigest() != record.get('sha256'):
        raise RecoveryError('Legacy backup integrity mismatch')
    return data
