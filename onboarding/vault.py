"""Bounded, authenticated v1 recovery vaults and explicit minimal key export."""
import base64
from contextlib import contextmanager
import json
import os
from pathlib import Path
from . import PrerequisiteError
import secrets
import tempfile
import uuid

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.scrypt import Scrypt

FORMAT = 'qrio-sl1-owner-credential-v1'
MAX_BLOB = 65536
EXPORT_FIELDS = ('version', 'state', 'phone_uuid', 'lock_uuid', 'signing_private_pem',
                 'mq_public', 'challenge_a', 'challenge_b')


def _key(salt, passphrase):
    if not isinstance(passphrase, str) or not 0 < len(passphrase.encode('utf-8')) <= 4096:
        raise PrerequisiteError('Invalid passphrase length')
    return Scrypt(salt=salt, length=32, n=2**15, r=8, p=1).derive(passphrase.encode('utf-8'))


def validate_record(record, coefficients=None):
    if not isinstance(record, dict) or type(record.get('version')) is not int or record['version'] != 1:
        raise PrerequisiteError('Unsupported owner record')
    if record.get('state') not in ('pending', 'acknowledged', 'registered', 'verified'):
        raise PrerequisiteError('Unsupported enrollment state')
    for field in ('lock_uuid', 'mq_public', 'mq_private', 'challenge_a', 'challenge_b'):
        value = record.get(field)
        if not isinstance(value, str) or len(value) != 32 or len(bytes.fromhex(value)) != 16:
            raise PrerequisiteError('Invalid owner key field')
    if str(uuid.UUID(record['phone_uuid'])) != record['phone_uuid']:
        raise PrerequisiteError('Invalid owner identity')
    for field in ('signing_private_pem', 'storage_private_pem'):
        value = record.get(field)
        if not isinstance(value, str) or len(value) > 4096:
            raise PrerequisiteError('Invalid owner private key')
        key = serialization.load_pem_private_key(value.encode('ascii'), password=None)
        if not isinstance(key, rsa.RSAPrivateKey) or key.key_size != 2048 or key.public_key().public_numbers().e != 65537:
            raise PrerequisiteError('Expected RSA-2048 with exponent 65537')
    if coefficients is not None:
        from .mq import public_from_private
        if not secrets.compare_digest(public_from_private(bytes.fromhex(record['mq_private']), coefficients),
                                      bytes.fromhex(record['mq_public'])):
            raise PrerequisiteError('MQ keypair does not match this APK')


def encrypt_vault(record, passphrase):
    validate_record(record)
    plain = json.dumps(record, sort_keys=True, separators=(',', ':')).encode('utf-8')
    if len(plain) > 32752:
        raise PrerequisiteError('Owner record too large')
    salt, nonce = secrets.token_bytes(16), secrets.token_bytes(12)
    cipher = AESGCM(_key(salt, passphrase)).encrypt(nonce, plain, FORMAT.encode('ascii'))
    envelope = {'format': FORMAT, **{k: base64.b64encode(v).decode('ascii')
                for k, v in (('salt', salt), ('nonce', nonce), ('ciphertext', cipher))}}
    return json.dumps(envelope, sort_keys=True, separators=(',', ':')).encode('ascii') + b'\n'


def decrypt_vault(blob, passphrase):
    try:
        if not 0 < len(blob) <= MAX_BLOB:
            raise PrerequisiteError()
        envelope = json.loads(blob)
        if envelope['format'] != FORMAT:
            raise PrerequisiteError()
        salt, nonce, cipher = [base64.b64decode(envelope[k], validate=True)
                               for k in ('salt', 'nonce', 'ciphertext')]
        if len(salt) != 16 or len(nonce) != 12 or not 16 <= len(cipher) <= 32768:
            raise PrerequisiteError()
        plain = AESGCM(_key(salt, passphrase)).decrypt(nonce, cipher, FORMAT.encode('ascii'))
        record = json.loads(plain)
        validate_record(record)
        return record
    except Exception:
        raise PrerequisiteError('Vault could not be opened: wrong passphrase or invalid/damaged vault') from None


def read_vault(path, passphrase):
    with Path(path).open('rb') as source:
        blob = source.read(MAX_BLOB + 1)
    return decrypt_vault(blob, passphrase)


def _sync_directory(path):
    if os.name == 'posix':
        descriptor = os.open(path, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(descriptor)
        finally:
            os.close(descriptor)


def write_private(path, data):
    """Create without overwriting; POSIX 0600, Windows inherits directory ACL."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL | getattr(os, 'O_BINARY', 0), 0o600)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(data)
            output.flush()
            os.fsync(output.fileno())
        _sync_directory(path.parent)
    except BaseException:
        path.unlink(missing_ok=True)
        raise


def create_vault(path, record, passphrase):
    blob = encrypt_vault(record, passphrase)
    if decrypt_vault(blob, passphrase) != record:
        raise PrerequisiteError('Vault readback failed')
    write_private(path, blob)
    if read_vault(path, passphrase) != record:
        raise PrerequisiteError('Saved vault readback failed')


def update_vault(path, record, passphrase):
    path = Path(path)
    # Preserve exact prior ciphertext before every state change, including legacy import.
    with path.open('rb') as source:
        old = source.read(MAX_BLOB + 1)
    decrypt_vault(old, passphrase)
    blob = encrypt_vault(record, passphrase)
    if decrypt_vault(blob, passphrase) != record:
        raise PrerequisiteError('Vault readback failed')
    write_private(path.with_name(path.name + '.backup-' + secrets.token_hex(6)), old)
    descriptor, name = tempfile.mkstemp(prefix='.qsl1-', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(descriptor, 'wb') as output:
            output.write(blob)
            output.flush()
            os.fsync(output.fileno())
        if read_vault(temporary, passphrase) != record:
            raise PrerequisiteError('Temporary vault readback failed')
        os.replace(temporary, path)
        _sync_directory(path.parent)
    finally:
        temporary.unlink(missing_ok=True)


@contextmanager
def vault_lock(path):
    """OS-released lock prevents concurrent enrollment/export of the same vault."""
    path = Path(path)
    path.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    descriptor = os.open(path.with_name(path.name + '.lock'), os.O_RDWR | os.O_CREAT, 0o600)
    acquired = False
    try:
        if os.name == 'nt':
            import msvcrt
            if os.fstat(descriptor).st_size == 0:
                os.write(descriptor, b'0')
            os.lseek(descriptor, 0, os.SEEK_SET)
            msvcrt.locking(descriptor, msvcrt.LK_NBLCK, 1)
        else:
            import fcntl
            fcntl.flock(descriptor, fcntl.LOCK_EX | fcntl.LOCK_NB)
        acquired = True
        yield
    finally:
        if acquired:
            if os.name == 'nt':
                os.lseek(descriptor, 0, os.SEEK_SET)
                msvcrt.locking(descriptor, msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(descriptor, fcntl.LOCK_UN)
        os.close(descriptor)


def export_owner(record, output):
    validate_record(record)
    if record['state'] != 'verified' or record.get('verification') != 'authenticated-read-status-v1':
        raise PrerequisiteError('Run verify successfully before exporting an operation key')
    subset = {field: record[field] for field in EXPORT_FIELDS}
    subset['state'] = 'registered'  # Existing HomeKit gateway input format.
    write_private(output, json.dumps(subset, sort_keys=True, separators=(',', ':')).encode('utf-8') + b'\n')
