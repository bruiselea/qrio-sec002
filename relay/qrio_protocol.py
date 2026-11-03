"""Q-SL1 operation framing and existing-owner authentication (MIT).

Pure protocol code only: no enrollment, APK/SDK loading, filesystem keys or I/O
on import. Owner private data must be supplied at runtime by its owner.
"""
from __future__ import annotations
import asyncio
from dataclasses import dataclass
import hashlib
import hmac
import struct
import uuid
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes


SERVICE_UUID = "466ab9a5-8129-5b97-5841-69c124fba0df"

WRITE_UUIDS = (
    "6ad0eefc-7279-b0a7-5748-e8921f9481ad",
    "7f93c949-ac1d-5d92-ed4a-240625a47ab2",
    "48ecf5db-98c2-d299-534c-6258899dfa84",
    "687053a8-a2b8-3087-174b-b5d3bf8a06b6",
)

NOTIFY_UUID = "cab18634-6b0f-1ab7-e047-a3dddd6730df"

QRIO_COMPANY_ID = 0x0235

@dataclass(frozen=True)
class LockAdvertisement:
    device: object
    serial: str
    lock_uuid_bytes: bytes

def parse_lock_advertisement(device: object, advertisement: object) -> LockAdvertisement | None:
    payload = advertisement.manufacturer_data.get(QRIO_COMPANY_ID)
    if payload is None or len(payload) < 20:
        return None
    # This lock also advertises its name/manufacturer identity without a
    # service UUID. Require Qrio identity data plus either its name or UUID;
    # operational clients still match the registered 128-bit lock identity.
    name = advertisement.local_name or getattr(device, "name", None)
    if SERVICE_UUID not in advertisement.service_uuids and name != "Q-SL1":
        return None
    serial_bytes = payload[16:20]
    serial = f"S01-{serial_bytes[0]:X}{serial_bytes[1]:02X}{serial_bytes[2]:02X}{serial_bytes[3]:02X}"
    return LockAdvertisement(device, serial, bytes(payload[:16]))

def frame_message(body: bytes) -> list[bytes]:
    packet = struct.pack("<H", len(body)) + body
    chunks = [packet[index : index + 19] for index in range(0, len(packet), 19)]
    if not 1 <= len(chunks) <= 127:
        raise ValueError("Message has an unsupported fragment count")
    return [bytes([((0x80 | len(chunks)) if index == 0 else index)]) + chunk.ljust(19, b"\0")
            for index, chunk in enumerate(chunks)]

async def send_message(client: BleakClient, body: bytes) -> None:
    for index, frame in enumerate(frame_message(body)):
        await client.write_gatt_char(WRITE_UUIDS[index % len(WRITE_UUIDS)], frame, response=False)

async def receive_message(queue: asyncio.Queue[bytes], timeout: float = 7.0) -> bytes:
    fragments: list[bytes] = []
    total: int | None = None
    while total is None or len(fragments) < total:
        frame = await asyncio.wait_for(queue.get(), timeout=timeout)
        if len(frame) < 2:
            continue
        header = frame[0]
        if header & 0x80:
            total = header & 0x7F
            fragments = [frame[1:]]
        elif total is not None and header == len(fragments):
            fragments.append(frame[1:])
        else:
            raise RuntimeError("Unexpected notification fragment order")
        if total == 0:
            raise RuntimeError("Empty notification frame")
    packet = b"".join(fragments)
    if len(packet) < 2:
        raise RuntimeError("Short notification packet")
    body_length = struct.unpack_from("<H", packet)[0]
    if body_length > len(packet) - 2:
        raise RuntimeError("Notification length exceeds received data")
    return packet[2 : 2 + body_length]

def mac(key: bytes, *parts: bytes) -> bytes:
    digest = hmac.new(key, digestmod=hashlib.sha256)
    for part in parts:
        digest.update(part)
    return digest.digest()

def uuid_bytes(value: uuid.UUID) -> bytes:
    """Match Java ByteBuffer's little-endian UUID layout in the archived app."""
    return value.bytes[8:][::-1] + value.bytes[:8][::-1]

def java_big_integer_bytes(value: int) -> bytes:
    """Match positive BigInteger.toByteArray(), including its sign byte."""
    encoded = value.to_bytes((value.bit_length() + 7) // 8, "big")
    return b"\x00" + encoded if encoded[0] & 0x80 else encoded

CERT_CONTEXT = b"\x01\x00\x00\x01"

def aes_encrypt(key: bytes, plaintext: bytes) -> bytes:
    if len(plaintext) % 16:
        raise ValueError("Q-SL1 operation certificate is not AES block aligned")
    cipher = Cipher(algorithms.AES(key), modes.ECB()).encryptor()
    return cipher.update(plaintext) + cipher.finalize()

def owner_credential(record: dict[str, object],
                     signing_key: rsa.RSAPrivateKey) -> tuple[bytes, bytes, bytes, bytes]:
    """Recreate the owner certificate produced by old-app setup/owner/i1."""
    lock_id = bytes.fromhex(str(record["lock_uuid"]))
    phone_id = uuid_bytes(uuid.UUID(str(record["phone_uuid"])))
    certificate_id = uuid_bytes(uuid.uuid4())
    modulus = java_big_integer_bytes(signing_key.public_key().public_numbers().n)
    mq_public = bytes.fromhex(str(record["mq_public"]))
    if len(modulus) != 257 or len(mq_public) != 16:
        raise ValueError("Owner public key has an unexpected length")
    # lib/ru/a: version, revision, certificate UUID, lock UUID, device UUID
    # twice, all 14 permissions, unrestricted condition, RSA modulus, MQ key.
    serialized = (b"\x01" + struct.pack("<I", 1) + certificate_id + lock_id +
                  phone_id + phone_id + struct.pack("<Q", (1 << 14) - 1) +
                  b"\x00" * 17 + modulus + mq_public)
    if len(serialized) != 367:
        raise AssertionError("Owner certificate serialization length changed")
    root_a = bytes.fromhex(str(record["challenge_a"]))
    root_b = bytes.fromhex(str(record["challenge_b"]))
    signature = signing_key.sign(CERT_CONTEXT + b"\x01" + serialized,
                                 padding.PKCS1v15(), hashes.SHA256())
    proof = mac(root_b, CERT_CONTEXT, b"\x00", serialized)
    # lib/ru/n creates per-device operation keys from the registered root.
    digest = hashes.Hash(hashes.SHA256())
    digest.update(b"\xff" * 5 + root_a + root_b + phone_id)
    derived = digest.finalize()
    return serialized, signature + proof, derived[:16], phone_id

def operation_finish(signing_key: rsa.RSAPrivateKey, operation: int,
                     session: bytes, phone_nonce: bytes, lock_nonce: bytes,
                     lock_id: bytes, phone_id: bytes) -> bytes:
    if (len(session), len(phone_nonce), len(lock_nonce), len(lock_id), len(phone_id)) != (
            1, 32, 32, 16, 16):
        raise ValueError("Operation authentication field lengths do not match the stock app")
    signed = (b"\x01\x02" + bytes([operation]) + session + b"\x01" +
              phone_nonce + lock_nonce + lock_id + phone_id)
    signature = signing_key.sign(signed, padding.PKCS1v15(), hashes.SHA256())
    return b"\x02\x03" + phone_nonce + signature
