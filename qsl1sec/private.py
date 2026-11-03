"""Portable encrypted backups; plaintext never leaves local process memory."""

import base64
from datetime import datetime, timezone
import json
import os
from pathlib import Path

from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt
from cryptography.exceptions import InvalidTag

FORMAT = 'qsl1sec-private-v1'


def invoking_owner(path):
    """Allow the sudo caller to copy their own encrypted backup off the Pi."""
    if os.name == 'posix' and os.geteuid() == 0 and os.environ.get('SUDO_UID', '').isdigit() and os.environ.get('SUDO_GID', '').isdigit():
        os.chown(path, int(os.environ['SUDO_UID']), int(os.environ['SUDO_GID']))


def derive(password, salt):
    if len(password) < 12:
        raise ValueError('Backup passphrase must contain at least 12 characters')
    return Scrypt(salt=salt, length=32, n=32768, r=8, p=1).derive(password.encode('utf-8'))


def seal(payload, password):
    salt, nonce = os.urandom(16), os.urandom(12)
    plain = json.dumps(payload, separators=(',', ':'), sort_keys=True).encode('utf-8')
    created = datetime.now(timezone.utc).isoformat()
    encrypted = AESGCM(derive(password, salt)).encrypt(nonce, plain, (FORMAT + '|' + created).encode())
    return {'format': FORMAT, 'created_utc': created,
            'salt': base64.b64encode(salt).decode(), 'nonce': base64.b64encode(nonce).decode(),
            'ciphertext': base64.b64encode(encrypted).decode()}


def open_envelope(record, password):
    if record.get('format') != FORMAT:
        raise ValueError('Unexpected private-backup format')
    salt, nonce, ciphertext = (base64.b64decode(record[k], validate=True) for k in ('salt', 'nonce', 'ciphertext'))
    if len(salt) != 16 or len(nonce) != 12 or not 16 <= len(ciphertext) <= 180000:
        raise ValueError('Invalid backup envelope sizes')
    created = record.get('created_utc')
    if not isinstance(created, str) or len(created) > 64:
        raise ValueError('Invalid backup timestamp')
    try:
        plain = AESGCM(derive(password, salt)).decrypt(nonce, ciphertext, (FORMAT + '|' + created).encode())
    except InvalidTag:
        raise ValueError('Incorrect passphrase or corrupted backup') from None
    return json.loads(plain)


def save(path, payload, password):
    path = Path(path)
    try:
        path.parent.mkdir(parents=True, mode=0o700)
    except FileExistsError:
        pass
    else:
        invoking_owner(path.parent)
    record = seal(payload, password)
    encoded = json.dumps(record, separators=(',', ':')).encode()
    # Never overwrite a known-good recovery backup.
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, 'wb') as stream:
        stream.write(encoded)
        stream.flush()
        os.fsync(stream.fileno())
    invoking_owner(path)
    if load(path, password) != payload:
        raise ValueError('Saved backup failed decryption verification')


def load(path, password):
    path = Path(path)
    if path.stat().st_size > 250000:
        raise ValueError('Backup envelope exceeds size limit')
    return open_envelope(json.loads(path.read_text(encoding='utf-8')), password)
