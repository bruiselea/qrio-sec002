"""Load only the sibling public runtime; never the private analysis workspace."""
from pathlib import Path
from . import PrerequisiteError
import sys

RELAY = Path(__file__).resolve().parents[1] / 'relay'
# The published relay programs use flat imports when invoked as scripts.
sys.path.insert(0, str(RELAY))
import qrio_protocol as protocol
from qrio_live import QrioLive


async def discover(serial, relay_config=None, seconds=10):
    """Match a card serial; collect the full scan so ambiguity fails closed."""
    import asyncio
    found = {}
    target = serial.split('-')[1]

    def collect(advertisement):
        if advertisement is not None and advertisement.serial.split('-')[1] == target:
            found[advertisement.lock_uuid_bytes] = advertisement

    if relay_config is None:
        from bleak import BleakScanner
        def callback(device, advertisement):
            collect(protocol.parse_lock_advertisement(device, advertisement))
        async with BleakScanner(detection_callback=callback):
            await asyncio.sleep(seconds)
    else:
        from aioesphomeapi import APIClient
        from qrio_esphome_transport import RelayConfig, manufacturer_data
        config = RelayConfig.load(relay_config)
        api = APIClient(config.host, 6053, None, noise_psk=config.noise_psk,
                        expected_mac=config.expected_mac.replace(':', '').lower(),
                        client_info='Q-SL1 owner enrollment discovery')
        unsubscribe = None
        try:
            async with asyncio.timeout(12):
                await api.connect(login=True)
                info = await api.device_info()
            if info.mac_address.upper() != config.expected_mac:
                raise PrerequisiteError('Relay identity mismatch')
            def callback(batch):
                for advertisement in batch.advertisements:
                    payload = manufacturer_data(advertisement.data).get(0x235, b'')
                    if len(payload) >= 20:
                        identity = bytes(payload[:16])
                        base = f'S01-{payload[16]:X}{payload[17]:02X}{payload[18]:02X}{payload[19]:02X}'
                        collect(protocol.LockAdvertisement(None, base, identity))
            unsubscribe = api.subscribe_bluetooth_le_raw_advertisements(callback)
            await asyncio.sleep(seconds)
        finally:
            if unsubscribe is not None:
                unsubscribe()
            async with asyncio.timeout(5):
                await api.disconnect()
    if len(found) != 1:
        raise PrerequisiteError('Expected exactly one advertised Q-SL1 matching the card')
    return next(iter(found.values()))
