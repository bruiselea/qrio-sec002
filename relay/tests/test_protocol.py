import asyncio
import struct
import unittest
import uuid

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import padding, rsa
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from qrio_protocol import (owner_credential, operation_finish, aes_encrypt,
                           frame_message, receive_message, mac, CERT_CONTEXT)


class ProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def test_fragment_roundtrip_and_bad_sequence(self):
        body=bytes(range(256))*3
        frames=frame_message(body)
        self.assertTrue(all(len(f)==20 for f in frames))
        queue=asyncio.Queue()
        for frame in frames:queue.put_nowait(frame)
        self.assertEqual(await receive_message(queue),body)
        bad=asyncio.Queue();bad.put_nowait(frames[0]);bad.put_nowait(frames[2])
        with self.assertRaises(RuntimeError):await receive_message(bad)

    async def test_owner_certificate_and_encrypted_operation_contract(self):
        key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
        record={'lock_uuid':'00112233445566778899aabbccddeeff',
                'phone_uuid':str(uuid.UUID(int=1)), 'mq_public':'ab'*16,
                'challenge_a':'01'*16,'challenge_b':'02'*16}
        certificate,proof,aes_key,phone=owner_credential(record,key)
        self.assertEqual(len(certificate),367)
        self.assertEqual(len(proof),288)
        key.public_key().verify(proof[:256],CERT_CONTEXT+b'\x01'+certificate,padding.PKCS1v15(),hashes.SHA256())
        self.assertEqual(proof[256:],mac(bytes.fromhex(record['challenge_b']),CERT_CONTEXT,b'\0',certificate))
        encoded=aes_encrypt(aes_key,b'\x06'+certificate)
        decryptor=Cipher(algorithms.AES(aes_key),modes.ECB()).decryptor()
        self.assertEqual(decryptor.update(encoded)+decryptor.finalize(),b'\x06'+certificate)
        session=b'\x03';nonce=bytes(32);challenge=bytes([1])*32;lock=bytes.fromhex(record['lock_uuid'])
        finish=operation_finish(key,6,session,nonce,challenge,lock,phone)
        self.assertEqual(finish[:34],b'\x02\x03'+nonce)
        signed=b'\x01\x02\x06'+session+b'\x01'+nonce+challenge+lock+phone
        key.public_key().verify(finish[34:],signed,padding.PKCS1v15(),hashes.SHA256())

    async def test_status_worker_rejects_firmware_operation(self):
        from qrio_live import QrioLive
        worker=object.__new__(QrioLive);worker.relay_config=None
        with self.assertRaises(ValueError):await worker.authenticate(9)

