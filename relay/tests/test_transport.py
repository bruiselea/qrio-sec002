"""Offline relay tests; no BLE, Wi-Fi, owner credential or motor traffic."""

import asyncio
import base64
import json
from pathlib import Path
from types import SimpleNamespace as NS
import tempfile
import unittest
from unittest.mock import patch
import sys
from enum import IntFlag

from qrio_esphome_transport import RemoteGATT, RelayConfig, SERVICE_UUID, WRITE_UUIDS, NOTIFY_UUID, manufacturer_data

IDENTITY = '00112233445566778899aabbccddeeff'


def service():
    return NS(uuid=SERVICE_UUID,characteristics=[NS(uuid=u,handle=i+10,properties=0x10 if u==NOTIFY_UUID else 4)
                                               for i,u in enumerate((*WRITE_UUIDS,NOTIFY_UUID))])


class FakeAPI:
    def __init__(self):
        self.writes=[]
        self.disconnects=0

    def subscribe_bluetooth_le_raw_advertisements(self,callback):
        self.callback=callback
        self.unsubscribed=False
        return lambda:setattr(self,'unsubscribed',True)

    async def bluetooth_gatt_write(self,*args,**kwargs):
        self.writes.append((args,kwargs))

    async def bluetooth_device_disconnect(self,*args,**kwargs):
        self.disconnects+=1

    async def disconnect(self):
        self.closed=True


class Tests(unittest.IsolatedAsyncioTestCase):
    def relay(self):
        config=RelayConfig('192.168.1.123',base64.b64encode(bytes(32)).decode(),'00:11:22:33:44:55')
        r=RemoteGATT(config,IDENTITY,scan_seconds=0.05)
        r.api=FakeAPI()
        return r

    async def test_scan_ignores_wrong_identity_and_cleans_subscription(self):
        r=self.relay();task=asyncio.create_task(r._find());await asyncio.sleep(0)
        wrong=NS(data=b'\x17\xff\x35\x02'+bytes(20),address=1,address_type=0,rssi=-45)
        r.api.callback(NS(advertisements=[wrong]));await asyncio.sleep(0);self.assertFalse(task.done())
        wanted=NS(**{**wrong.__dict__,'data':b'\x17\xff\x35\x02'+bytes.fromhex(IDENTITY)+bytes(4)})
        r.api.callback(NS(advertisements=[wanted]));await task
        self.assertEqual(r.peer,1);self.assertFalse(r.api.unsubscribed)
        api=r.api;await r.disconnect();self.assertTrue(api.unsubscribed)

    async def test_raw_advertisement_parser_rejects_malformed_and_duplicate_data(self):
        good=b'\x17\xff\x35\x02'+bytes.fromhex(IDENTITY)+bytes(4)
        self.assertEqual(manufacturer_data(good)[0x235],bytes.fromhex(IDENTITY)+bytes(4))
        for packet in (good[:-1],good+good,b'\x01\xff',bytes(63)):
            self.assertEqual(manufacturer_data(packet),{})

    async def test_scan_timeout_and_cancellation_release_subscription(self):
        for cancel in (False,True):
            r=self.relay();task=asyncio.create_task(r._find());await asyncio.sleep(0)
            if cancel:task.cancel()
            with self.assertRaises(asyncio.CancelledError if cancel else TimeoutError):await task
            self.assertTrue(r.api.unsubscribed)

    async def test_service_scope_and_gatt_write_limits(self):
        r=self.relay();r._bind_services([service()]);r.is_connected=True;r.peer=1
        for uuid,data,response in ((SERVICE_UUID,bytes(20),False),(NOTIFY_UUID,bytes(20),False),
                                   (WRITE_UUIDS[0],bytes(19),False),(WRITE_UUIDS[0],bytes(20),True)):
            with self.assertRaises(ValueError):await r.write_gatt_char(uuid,data,response)
        self.assertEqual(r.api.writes,[])
        await r.write_gatt_char(WRITE_UUIDS[0],bytes(20))
        self.assertEqual(len(r.api.writes),1)
        r._connection_changed(False,23,0)
        with self.assertRaises(ValueError):await r.write_gatt_char(WRITE_UUIDS[0],bytes(20))
        self.assertEqual(len(r.api.writes),1)
        for items in ([],[service(),service()]):
            with self.assertRaises(RuntimeError):r._bind_services(items)

    async def test_no_write_replay_after_network_failure(self):
        r=self.relay();r._bind_services([service()]);r.is_connected=True;r.peer=1
        async def lost(*args,**kwargs):
            r.api.writes.append(args);raise TimeoutError('synthetic lost delivery')
        r.api.bluetooth_gatt_write=lost
        with self.assertRaises(TimeoutError):await r.write_gatt_char(WRITE_UUIDS[0],bytes(20))
        self.assertEqual(len(r.api.writes),1)

    async def test_cleanup_even_when_ble_already_disconnected(self):
        r=self.relay();api=r.api;r.peer=1;r.is_connected=False
        r._bind_services([service()]);await r.disconnect();await r.disconnect()
        self.assertTrue(api.closed);self.assertEqual(api.disconnects,1);self.assertEqual(r.handles,{})

    async def test_config_requires_encryption_lan_and_relay_identity(self):
        r=self.relay();valid=r.config.__dict__
        with tempfile.TemporaryDirectory() as folder:
            p=Path(folder)/'config.json'
            for edit in ({},{'host':'8.8.8.8'},{'noise_psk':''},{'expected_mac':'invalid'}):
                p.write_text(json.dumps({**valid,**edit}),encoding='utf-8');p.chmod(0o600)
                if edit:
                    with self.assertRaises(ValueError):RelayConfig.load(p)
                else:self.assertEqual(RelayConfig.load(p),r.config)

    async def test_full_open_checks_relay_identity_pairs_then_binds_notifications(self):
        class Features(IntFlag):
            ACTIVE_CONNECTIONS=2
            REMOTE_CACHING=4
            PAIRING=8
            RAW_ADVERTISEMENTS=32
        class FullAPI(FakeAPI):
            def __init__(self,*args,**kwargs):
                super().__init__();self.kwargs=kwargs;self.api_version=1
                self.bad_mac=False;self.pair_ok=True;self.pair_calls=0;self.subscriptions=0
                self.connection_calls=0
            async def connect(self,login):self.login=login
            async def device_info(self):
                return NS(mac_address='00:11:22:33:44:66' if self.bad_mac else '00:11:22:33:44:55',
                          bluetooth_proxy_feature_flags_compat=lambda _:46)
            def subscribe_bluetooth_le_raw_advertisements(self,callback):
                self.subscriptions+=1
                unsub=super().subscribe_bluetooth_le_raw_advertisements(callback)
                adv=NS(data=b'\x17\xff\x35\x02'+bytes.fromhex(IDENTITY)+bytes(4),
                       address=1,address_type=0,rssi=-55)
                asyncio.get_running_loop().call_soon(callback,NS(advertisements=[adv]))
                return unsub
            async def bluetooth_device_connect(self,address,callback,**kwargs):
                if self.unsubscribed:raise RuntimeError('GATT reply routing requires the active subscriber')
                self.connection_calls+=1
                callback(True,23,0);return lambda:None
            async def bluetooth_device_unpair(self,*args,**kwargs):
                if self.connection_calls:raise RuntimeError('Bond refresh on a live link can drop it')
                return NS(success=True,error=0)
            async def bluetooth_device_pair(self,*args,**kwargs):
                self.pair_calls+=1;return NS(paired=self.pair_ok,error=0 if self.pair_ok else 1)
            async def bluetooth_gatt_get_services(self,*args):return NS(services=[service()])
            async def bluetooth_gatt_start_notify(self,peer,handle,callback,**kwargs):
                self.notify=callback
                return lambda:asyncio.sleep(0),lambda:setattr(self,'notify',None)
        models={'aioesphomeapi':NS(),'aioesphomeapi.model':NS(BluetoothProxyFeature=Features)}
        for failure in ('none','identity','pairing'):
            r=self.relay();api=FullAPI();api.bad_mac=failure=='identity';api.pair_ok=failure!='pairing'
            received={}
            def factory(*args,**kwargs):received.update(kwargs);return api
            r.api_factory=factory;r.reset_pairing=True
            with patch.dict(sys.modules,models):
                if failure!='none':
                    with self.assertRaises(RuntimeError):await r.open()
                    self.assertTrue(api.closed);self.assertEqual(api.writes,[])
                    if failure=='identity':self.assertEqual(api.subscriptions,0)
                    continue
                await r.open()
                self.assertEqual(received['expected_mac'],'001122334455')
                self.assertEqual(api.pair_calls,1)
                notifications=[]
                await r.start_notify(NOTIFY_UUID,lambda handle,data:notifications.append(data))
                api.notify(999,bytearray(20));self.assertEqual(notifications,[])
                api.notify(r.handles[NOTIFY_UUID],bytearray(20));self.assertEqual(len(notifications),1)
                await r.disconnect();self.assertTrue(api.closed)


if __name__=='__main__':unittest.main()
