"""Authenticated Q-SL1 operations for the local HomeKit bridge.

No enrollment, raw memory access or firmware commands. Mutating commands are
never automatically retried. Reuses the already verified owner certificate,
nonce/signature and framing implementation.
"""

import argparse
import asyncio
from datetime import datetime
import json
import os
from pathlib import Path
import secrets
import re
import struct
import sys
from zoneinfo import ZoneInfo

from bleak import BleakClient, BleakScanner
from cryptography.hazmat.primitives import serialization

from qrio_protocol import NOTIFY_UUID, SERVICE_UUID, parse_lock_advertisement, send_message, receive_message
from qrio_protocol import owner_credential, aes_encrypt, operation_finish


class QrioLive:
    def __init__(self, record, scan_seconds=7, reset_pairing=False, relay_config=None):
        self.record = record
        self.scan_seconds = scan_seconds
        self.reset_pairing = reset_pairing
        self.relay_config = relay_config
        self.relay = None
        self.key = serialization.load_pem_private_key(record["signing_private_pem"].encode(), password=None)
        self.certificate, self.proof, self.operation_key, self.phone_id = owner_credential(record, self.key)
        self.queue = asyncio.Queue()
        self.client = None
        self.agent = None
        self.stage = "idle"

    async def __aenter__(self):
        if self.relay_config is not None:
            from types import SimpleNamespace
            from qrio_esphome_transport import RemoteGATT, RelayConfig
            self.stage = "connecting"
            try:
                self.relay = RemoteGATT(RelayConfig.load(self.relay_config), self.record["lock_uuid"],
                                        scan_seconds=self.scan_seconds, reset_pairing=self.reset_pairing)
                self.client = await self.relay.open()
                self.lock = SimpleNamespace(lock_uuid_bytes=bytes.fromhex(self.record["lock_uuid"]))
                self.stage = "subscribing"
                await self.client.start_notify(NOTIFY_UUID, lambda _, data: self.queue.put_nowait(bytes(data)))
                return self
            except BaseException:
                await self.__aexit__(None, None, None)
                raise
        self.stage = "scanning"
        await self.find_lock()
        if self.reset_pairing:
            self.stage = "refreshing_pairing"
            await BleakClient(self.lock.device).unpair()
            # RemoveDevice has completed; wait for a fresh owned advertisement
            # instead of imposing another fixed one-second pause.
            await self.find_lock()
        if sys.platform == "linux":
            from bluez_qrio_agent import PairingAgent
            self.agent = PairingAgent()
            await self.agent.start(self.lock.device.details["path"])
        self.stage = "connecting"
        self.client = BleakClient(self.lock.device, pair=True, timeout=30)
        try:
            await self.client.connect()
            if self.client.services.get_service(SERVICE_UUID) is None:
                raise RuntimeError("Expected Q-SL1 GATT service was not present")
            loop = asyncio.get_running_loop()
            def notify(_characteristic, data):
                loop.call_soon_threadsafe(self.queue.put_nowait, bytes(data))
            self.stage = "subscribing"
            await self.client.start_notify(NOTIFY_UUID, notify)
        except BaseException:
            await self.__aexit__(None, None, None)
            raise
        return self

    async def find_lock(self):
        match = None
        def wanted(device, advertisement):
            nonlocal match
            parsed = parse_lock_advertisement(device, advertisement)
            if parsed is not None and parsed.lock_uuid_bytes.hex() == self.record["lock_uuid"]:
                match = parsed
                return True
            return False
        await BleakScanner.find_device_by_filter(wanted, timeout=self.scan_seconds)
        if match is None:
            raise RuntimeError("Registered Q-SL1 was not found")
        self.lock = match

    async def __aexit__(self, *error):
        try:
            if self.relay is not None:
                await self.relay.disconnect()
            elif self.client is not None and self.client.is_connected:
                await self.client.disconnect()
        except Exception:
            pass
        finally:
            if self.agent is not None:
                try:
                    await self.agent.close()
                except Exception:
                    pass

    async def exchange(self, body, timeout=10):
        await send_message(self.client, body)
        response = await receive_message(self.queue, timeout=timeout)
        if not response or response[0] != 0:
            raise RuntimeError(f"Q-SL1 rejected {self.stage}: status={response[0] if response else -1}")
        return response[1:]

    async def authenticate(self, operation, query=b"\0\0"):
        if self.relay_config is not None and operation not in (0, 1, 6):
            raise ValueError("Relay supports only lock, unlock and read-only status")
        if operation not in (0, 1, 6):
            raise ValueError("Only unlock, lock and read-only status are enabled")
        self.stage = "auth_start"
        start = await self.exchange(b"\x02\x00" + self.phone_id + self.phone_id)
        if not start:
            raise RuntimeError("Operation start response lacked its session")
        self.stage = "certificate"
        await self.exchange(b"\x02\x01" + aes_encrypt(self.operation_key, bytes([operation]) + self.certificate))
        self.stage = "owner_proof"
        nonce = await self.exchange(b"\x02\x02" + self.proof + struct.pack("<h", 540) + query)
        if len(nonce) != 32:
            raise RuntimeError("Expected a 32-byte lock nonce")
        self.stage = "operation_signature"
        return await self.exchange(operation_finish(self.key, operation, start[:1], secrets.token_bytes(32),
            nonce, self.lock.lock_uuid_bytes, self.phone_id), timeout=20)

    async def settings(self):
        result = await self.authenticate(6, b"\x01\x00")
        if len(result) < 6:
            raise RuntimeError("Settings reply was too short")
        return result

    async def actuate(self, locked):
        await self.authenticate(1 if locked else 0)
        now = datetime.now(ZoneInfo("Asia/Tokyo"))
        self.stage = "actuating"
        command = b"\x02\x05\x00" + struct.pack("<HBBBBB", now.year, now.month, now.day,
                                                      now.hour, now.minute, now.second)
        result = await self.exchange(command, timeout=20)
        return result


async def cli(args):
    record = json.loads(args.credential.read_text())
    connection = QrioLive(record, reset_pairing=args.reset_pairing,
                          relay_config=getattr(args, "relay_config", None))
    try:
        async with connection:
            if args.action == "status":
                result = await connection.settings()
                print(json.dumps({"authenticated": True, "settings_fields": list(result)}), flush=True)
            else:
                result = await connection.actuate(args.action == "lock")
                print(json.dumps({"authenticated": True, "action": args.action, "result_fields": list(result)}), flush=True)
    except Exception as error:
        detail = ("Relay operation stopped: " + type(error).__name__) if connection.relay_config else str(error)
        detail = re.sub(r"(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}", "<device>", detail)
        detail = re.sub(r"[0-9A-Fa-f]{8}(?:-[0-9A-Fa-f]{4}){3}-[0-9A-Fa-f]{12}", "<uuid>", detail)
        print(json.dumps({"stage": connection.stage, "error_type": type(error).__name__,
                          "relay_stage": getattr(connection.relay, "stage", None),
                          "error": detail[:200] or type(error).__name__}), flush=True)
        return False
    return True


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("status", "lock", "unlock"))
    parser.add_argument("--credential", type=Path, required=True)
    parser.add_argument("--reset-pairing", action="store_true")
    parser.add_argument("--relay-config", type=Path, default=os.environ.get("QRIO_RELAY_CONFIG"),
                        help="Private ESPHome relay config; otherwise use local Bluetooth")
    args = parser.parse_args()
    sys.exit(0 if asyncio.run(cli(args)) else 1)
