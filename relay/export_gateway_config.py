"""Discover and authenticate a provisioned relay; save private Pi settings.

No connection to Q-SL1, owner-key handling, or actuation is performed here.
"""
import argparse
import asyncio
import ipaddress
import json
import os
from pathlib import Path
import re

from aioesphomeapi import APIClient
import yaml
from zeroconf.asyncio import AsyncServiceInfo, AsyncZeroconf


async def main(args):
    if not re.fullmatch(r'(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}', args.mac):
        raise ValueError('Expected the USB-confirmed Wi-Fi MAC of the relay')
    if args.output.exists():
        raise FileExistsError('Private gateway settings already exist; will not overwrite')
    if args.host:
        host = args.host
    else:
        zc = AsyncZeroconf()
        try:
            service = AsyncServiceInfo('_esphomelib._tcp.local.', 'qrio-door-relay._esphomelib._tcp.local.')
            if not await service.async_request(zc.zeroconf, 15000):
                raise RuntimeError('Relay mDNS not found; supply the reserved --host IPv4')
            hosts = [a for a in service.parsed_addresses() if ipaddress.ip_address(a).version == 4]
            if not hosts:
                raise RuntimeError('Relay advertised no IPv4 address')
            host = hosts[0]
        finally:
            await zc.async_close()
    address = ipaddress.IPv4Address(host)
    if not address.is_private or address.is_loopback or address.is_link_local or address.is_multicast:
        raise ValueError('Expected a private LAN relay address')
    values = yaml.safe_load((args.build_dir/'secrets.yaml').read_text(encoding='utf-8'))
    key = values['api_encryption_key']
    client = APIClient(str(address),6053,None,noise_psk=key,expected_mac=args.mac.replace(':','').lower())
    try:
        async with asyncio.timeout(15):
            await client.connect(login=True)
            info = await client.device_info()
        if info.mac_address.upper() != args.mac.upper() or info.name != 'qrio-door-relay':
            raise RuntimeError('Authenticated relay identity/name mismatch')
        data = {'host':str(address),'noise_psk':key,'expected_mac':args.mac.upper()}
        fd = os.open(args.output,os.O_WRONLY|os.O_CREAT|os.O_EXCL,0o600)
        with os.fdopen(fd,'w',encoding='utf-8') as f:
            json.dump(data,f)
        print(json.dumps({'encrypted_api_authenticated':True,'relay_version':info.esphome_version,
                          'private_gateway_settings_saved':True,'owner_keys_transferred':False}))
    finally:
        await client.disconnect()


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--build-dir',type=Path,required=True)
    parser.add_argument('--mac',required=True)
    parser.add_argument('--host')
    parser.add_argument('--output',type=Path,required=True)
    try:
        asyncio.run(main(parser.parse_args()))
    except Exception as error:
        # Library errors may contain local network identifiers; do not dump them.
        print('Relay setup stopped:',type(error).__name__)
        raise SystemExit(1) from None
