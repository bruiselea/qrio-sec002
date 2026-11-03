"""One-attempt card enrollment. No firmware, motor, memory or erase commands."""
import asyncio
import re
import secrets
import uuid

from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import padding, rsa

from . import EnrollmentError, PrerequisiteError
from .mq import generate_keypair
from .runtime import QrioLive, protocol
from .vault import create_vault, read_vault, update_vault, validate_record

CONTEXT = b'\x01\x01\x00\x00'
CARD_ALPHABET = '0123456789ABCDEFGHIJKMNOPQRSTUVWXYZ'


def normalize_serial(value):
    result = value.strip().upper()
    if not re.fullmatch(r'S01-[0-9A-F]{7}(?:-[A-Z])?', result):
        raise PrerequisiteError('Unsupported owner-card serial format')
    return result


def decode_card_code(value):
    digits = re.sub(r'[\s-]', '', value).upper()
    if len(digits) != 25 or any(digit not in CARD_ALPHABET for digit in digits):
        raise PrerequisiteError('Unsupported owner-card code format')
    number = 0
    for digit in digits:
        number = number * len(CARD_ALPHABET) + CARD_ALPHABET.index(digit)
    return (number & ((1 << 128) - 1)).to_bytes(16, 'big')


def prepare_record(advertisement, serial, coefficients):
    def pem():
        key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        return key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                 serialization.NoEncryption()).decode('ascii')
    private, public = generate_keypair(coefficients)
    return {'version': 1, 'state': 'pending', 'phase': 'prepared', 'serial': normalize_serial(serial),
            'lock_uuid': advertisement.lock_uuid_bytes.hex(), 'phone_uuid': str(uuid.uuid4()),
            'signing_private_pem': pem(), 'storage_private_pem': pem(),
            'mq_private': private.hex(), 'mq_public': public.hex(),
            'challenge_a': secrets.token_bytes(16).hex(), 'challenge_b': secrets.token_bytes(16).hex()}


def bind_record(record, advertisement, serial, coefficients):
    validate_record(record, coefficients)
    if (normalize_serial(record['serial']).split('-')[:2] != normalize_serial(serial).split('-')[:2]
            or advertisement.serial.split('-')[:2] != normalize_serial(serial).split('-')[:2]
            or record['lock_uuid'] != advertisement.lock_uuid_bytes.hex()):
        raise PrerequisiteError('Card, advertisement and saved vault do not identify the same Q-SL1')


async def exchange(connection, body, timeout):
    # Bound the entire exchange, including writes and repeated first fragments.
    async with asyncio.timeout(timeout):
        await protocol.send_message(connection.client, body)
        return await protocol.receive_message(connection.queue, timeout=timeout)


def accepted(reply, length, stage):
    if len(reply) < length or reply[0] != 0:
        status = reply[0] if reply else -1
        raise EnrollmentError(f'{stage} rejected (status={status})')


async def handshake(connection, card_key, record, save, progress=print):
    """Use saved keys only. Persist phase BEFORE the two key-writing messages."""
    phone = protocol.uuid_bytes(uuid.UUID(record['phone_uuid']))
    lock = bytes.fromhex(record['lock_uuid'])
    a, b = [bytes.fromhex(record[field]) for field in ('challenge_a', 'challenge_b')]
    reply = await exchange(connection, b'\x01\x00' + phone + protocol.aes_encrypt(card_key, a)
                           + protocol.aes_encrypt(card_key, b), 20)
    accepted(reply, 34, 'Registration start')
    if reply[1] != 0:
        raise EnrollmentError('Unsupported registration reply version')
    la, lb = reply[2:18], reply[18:34]
    pa, pb = secrets.token_bytes(16), secrets.token_bytes(16)
    reply = await exchange(connection, b'\x01\x01' + pa + pb
                           + protocol.mac(a, CONTEXT, b'\0', pa, la, lock, phone)
                           + protocol.mac(b, CONTEXT, b'\0', pb, lb, lock, phone), 20)
    accepted(reply, 65, 'Card challenge')
    if not (secrets.compare_digest(reply[1:33], protocol.mac(a, CONTEXT, b'\0', la, pa, phone, lock))
            and secrets.compare_digest(reply[33:65], protocol.mac(b, CONTEXT, b'\0', lb, pb, phone, lock))):
        raise EnrollmentError('Card challenge did not verify')
    progress('Card challenge verified. If the lock beeps, turn the knob over 90 degrees and back.')
    key = serialization.load_pem_private_key(record['signing_private_pem'].encode('ascii'), password=None)
    modulus = protocol.java_big_integer_bytes(key.public_key().public_numbers().n)
    public = bytes.fromhex(record['mq_public'])
    record.update(state='pending', phase='before-public-key')
    record.pop('verification', None)
    save(record)
    reply = await exchange(connection, b'\x01\x02' + modulus + public
                           + protocol.mac(b, CONTEXT, b'\0', modulus, public), 75)
    accepted(reply, 33, 'Public key')
    random = secrets.token_bytes(32)
    signature = key.sign(CONTEXT + b'\1' + random + reply[1:33] + lock + phone,
                         padding.PKCS1v15(), hashes.SHA256())
    record['phase'] = 'before-confirmation'
    save(record)
    reply = await exchange(connection, b'\x01\x03' + random + signature, 105)
    accepted(reply, 1, 'Physical confirmation')
    reply = await exchange(connection, b'\x01\x05', 40)
    accepted(reply, 1, 'Registration follow-up')
    record.update(state='acknowledged', phase='awaiting-authenticated-status')
    save(record)
    progress('Enrollment acknowledged. Checking saved keys on a new connection.')


async def verify_saved(path, passphrase, relay_config=None, factory=QrioLive):
    record = read_vault(path, passphrase)
    # A previous success does not survive a new failed verification.
    record.pop('verification', None)
    if record['state'] in ('verified', 'registered'):
        record['state'] = 'acknowledged'
    record['phase'] = 'verifying-status'
    update_vault(path, record, passphrase)
    async with asyncio.timeout(120):
        async with factory(record, reset_pairing=True, relay_config=relay_config) as connection:
            result = await connection.settings()
            if not isinstance(result, bytes) or len(result) < 6:
                raise EnrollmentError('Authenticated status reply was too short')
    record.update(state='verified', phase='complete', verification='authenticated-read-status-v1')
    update_vault(path, record, passphrase)
    return record


async def enroll_saved(advertisement, serial, card_key, coefficients, path, passphrase,
                       resume=False, relay_config=None, factory=QrioLive, progress=print):
    if resume:
        record = read_vault(path, passphrase)
        if record['state'] in ('verified', 'registered'):
            raise PrerequisiteError('Already registered: use verify, not another enrollment')
    else:
        record = prepare_record(advertisement, serial, coefficients)
    bind_record(record, advertisement, serial, coefficients)
    if not resume:
        create_vault(path, record, passphrase)
    progress('Encrypted recovery vault saved and read back before registration.')
    async with asyncio.timeout(330):
        async with factory(record, reset_pairing=True, relay_config=relay_config) as connection:
            await handshake(connection, card_key, record,
                            lambda value: update_vault(path, value, passphrase), progress)
    # Registration ACK alone is not proof that future operations authenticate.
    return await verify_saved(path, passphrase, relay_config, factory)
