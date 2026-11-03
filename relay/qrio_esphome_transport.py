"""A bounded Q-SL1 GATT transport over the encrypted ESPHome native API.

Owner authentication stays in QrioLive on the Pi. No automatic reconnect,
operation replay, arbitrary GATT access, firmware commands or key upload.
"""

import asyncio
import base64
from contextlib import suppress
from dataclasses import dataclass
import ipaddress
import json
import os
from pathlib import Path
import re

from qrio_protocol import SERVICE_UUID, NOTIFY_UUID, WRITE_UUIDS


def manufacturer_data(raw):
    """Strict BLE AD-structure parser for ESPHome's bounded raw adv payload."""
    data=bytes(raw)
    if len(data)>62:
        return {}
    result={};cursor=0
    while cursor<len(data):
        length=data[cursor]
        if not length:
            break
        end=cursor+1+length
        if end>len(data):
            return {}
        if data[cursor+1]==0xFF:
            if length<3:
                return {}
            company=int.from_bytes(data[cursor+2:cursor+4],'little')
            if company in result:
                return {}
            result[company]=data[cursor+4:end]
        cursor=end
    return result


@dataclass(frozen=True)
class RelayConfig:
    host: str
    noise_psk: str
    expected_mac: str

    @classmethod
    def load(cls, path):
        path = Path(path)
        if os.name == 'posix' and path.stat().st_mode & 0o077:
            raise ValueError('Relay config must be private (chmod 600 or systemd credential)')
        data = json.loads(path.read_text(encoding='utf-8'))
        host = ipaddress.IPv4Address(data['host'])
        if not host.is_private or host.is_loopback or host.is_link_local or host.is_multicast:
            raise ValueError('Relay must use a fixed private LAN IPv4 address')
        key = data['noise_psk']
        if not isinstance(key, str) or len(base64.b64decode(key, validate=True)) != 32:
            raise ValueError('Expected a 32-byte base64 ESPHome API encryption key')
        mac = data['expected_mac']
        if not isinstance(mac, str) or not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', mac):
            raise ValueError('Expected the relay Wi-Fi MAC from USB provisioning')
        return cls(str(host), key, mac.upper())


class RemoteGATT:
    def __init__(self, config, lock_uuid, scan_seconds=10, reset_pairing=False, api_factory=None):
        if not re.fullmatch(r'[0-9a-fA-F]{32}', lock_uuid):
            raise ValueError('Invalid registered lock identity')
        self.config, self.identity = config, bytes.fromhex(lock_uuid)
        self.scan_seconds, self.reset_pairing = scan_seconds, reset_pairing
        self.api_factory = api_factory
        self.api = self.peer = None
        self.is_connected = False
        self.handles = {}
        self._connection_unsub = self._notify_remove = None
        self._advertisement_unsub = None
        self.stage = 'idle'
        self.rssi = None

    async def open(self):
        if self.api_factory is None:
            from aioesphomeapi import APIClient
            self.api_factory = APIClient
        self.api = self.api_factory(self.config.host, 6053, None,
                                    noise_psk=self.config.noise_psk,
                                    expected_mac=self.config.expected_mac.replace(':', '').lower(),
                                    client_info='Q-SL1 owner gateway')
        try:
            self.stage = 'api_connect'
            async with asyncio.timeout(12):
                await self.api.connect(login=True)
                info = await self.api.device_info()
            if info.mac_address.upper() != self.config.expected_mac:
                raise RuntimeError('Relay identity mismatch')
            from aioesphomeapi.model import BluetoothProxyFeature
            flags = info.bluetooth_proxy_feature_flags_compat(self.api.api_version)
            required = (BluetoothProxyFeature.ACTIVE_CONNECTIONS | BluetoothProxyFeature.REMOTE_CACHING
                        | BluetoothProxyFeature.PAIRING | BluetoothProxyFeature.RAW_ADVERTISEMENTS)
            if flags & required != required:
                raise RuntimeError('Relay firmware lacks active GATT/cache/pairing support')
            self.stage = 'scanning'
            await self._find()
            if self.reset_pairing:
                self.stage = 'unpairing'
                unpaired = await self.api.bluetooth_device_unpair(self.peer, timeout=10)
                if not unpaired.success or unpaired.error:
                    raise RuntimeError('Relay BLE bond removal failed')
            # Bluedroid may terminate an encrypted link when its bond is
            # removed. Refresh it before connecting, never on the live link.
            self.stage = 'ble_connect'
            self._connection_unsub = await self.api.bluetooth_device_connect(
                self.peer, self._connection_changed, timeout=20, disconnect_timeout=3,
                feature_flags=flags, has_cache=False, address_type=self.address_type)
            if not self.is_connected:
                raise RuntimeError('Relay did not establish the selected BLE connection')
            self.stage = 'pairing'
            paired = await self.api.bluetooth_device_pair(self.peer, timeout=15)
            if not paired.paired or paired.error:
                raise RuntimeError('Relay BLE pairing failed')
            self.stage = 'services'
            async with asyncio.timeout(15):
                services = await self.api.bluetooth_gatt_get_services(self.peer)
            self._bind_services(services.services)
            return self
        except BaseException:
            await self.disconnect()
            raise

    async def _find(self):
        found = asyncio.get_running_loop().create_future()

        def advertisement(batch):
            for adv in batch.advertisements:
                data=manufacturer_data(adv.data).get(0x235,b'')
                # A raw advertising packet may not contain the scan-response
                # name. Bind the 128-bit identity here; check GATT below.
                if not found.done() and len(data)>=20 and data[:16]==self.identity:
                    found.set_result(adv)
        self._advertisement_unsub = self.api.subscribe_bluetooth_le_raw_advertisements(advertisement)
        try:
            adv = await asyncio.wait_for(found, self.scan_seconds)
            self.peer, self.address_type, self.rssi = adv.address, adv.address_type, adv.rssi
        except BaseException:
            self._advertisement_unsub()
            self._advertisement_unsub = None
            raise
        # ESPHome routes GATT replies to the advertising subscriber. Keep
        # this subscription for the entire session, not just discovery.

    def _connection_changed(self, connected, mtu, error):
        self.is_connected = bool(connected) and not error

    def _bind_services(self, services):
        wanted = [s for s in services if s.uuid.lower() == SERVICE_UUID]
        if len(wanted) != 1:
            raise RuntimeError('Expected exactly one Q-SL1 GATT service')
        handles = {}
        for uuid in (*WRITE_UUIDS, NOTIFY_UUID):
            matches = [c for c in wanted[0].characteristics if c.uuid.lower() == uuid]
            if len(matches) != 1 or not 0 < matches[0].handle <= 0xFFFF:
                raise RuntimeError('Missing or ambiguous Q-SL1 characteristic')
            if not matches[0].properties & (0x10 if uuid == NOTIFY_UUID else 0x04):
                raise RuntimeError('Q-SL1 characteristic properties differ')
            handles[uuid] = matches[0].handle
        if len(set(handles.values())) != len(handles):
            raise RuntimeError('Q-SL1 characteristic handles overlap')
        self.handles = handles

    async def start_notify(self, uuid, callback):
        self.stage = 'subscribing'
        if uuid != NOTIFY_UUID or not self.is_connected or self._notify_remove is not None:
            raise ValueError('Only the connected Q-SL1 notification is permitted')

        def received(handle, data):
            if self.is_connected and handle == self.handles[NOTIFY_UUID] and 2 <= len(data) <= 20:
                callback(handle, bytes(data))
        _, self._notify_remove = await self.api.bluetooth_gatt_start_notify(
            self.peer, self.handles[uuid], received, timeout=10)

    async def write_gatt_char(self, uuid, data, response=False):
        if (not self.is_connected or uuid not in WRITE_UUIDS or response is not False
                or len(data) != 20 or uuid not in self.handles):
            raise ValueError('Only connected Q-SL1 20-byte protocol frames are permitted')
        await self.api.bluetooth_gatt_write(self.peer, self.handles[uuid], bytes(data), response=False)
        # Bound the initial no-response burst over the shared Wi-Fi/BLE radio.
        await asyncio.sleep(0.02)

    async def disconnect(self):
        try:
            if self._notify_remove is not None:
                self._notify_remove()
                self._notify_remove = None
            if self.api is not None and self.peer is not None:
                with suppress(Exception):
                    await self.api.bluetooth_device_disconnect(self.peer, timeout=3)
        finally:
            self.is_connected = False
            self.handles.clear()
            if self._connection_unsub is not None:
                self._connection_unsub()
                self._connection_unsub = None
            if self._advertisement_unsub is not None:
                self._advertisement_unsub()
                self._advertisement_unsub = None
            if self.api is not None:
                with suppress(Exception):
                    async with asyncio.timeout(3):
                        await self.api.disconnect()
                self.api = None
