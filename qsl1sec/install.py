"""Fixed-image, page-safe wireless stage/activation. No network on import."""

import asyncio
import base64
from datetime import datetime, timezone
import json
from pathlib import Path
import struct

from .image import DS1, DS2, DS_SIZE, digest, validate_snapshot, plan, WritePolicy
from . import private
from .radio import BASE, REVISION, Session, connect


def progress(label):
    previous = [-1]

    def update(done, total):
        block = done // 4096
        if block != previous[0] or done == total:
            print(f'{label}: {done}/{total}', flush=True)
            previous[0] = block
    return update


def snapshot_payload(peer, identity, data):
    return {'kind': 'owned-eeprom-64k', 'address': peer, 'identity': identity,
            'bytes': len(data), 'sha256': digest(data), 'eeprom_b64': base64.b64encode(data).decode()}


def snapshot_data(payload):
    if payload.get('kind') != 'owned-eeprom-64k':
        raise ValueError('Expected an original EEPROM backup')
    data = base64.b64decode(payload['eeprom_b64'], validate=True)
    if len(data) != 65536 or payload.get('sha256') != digest(data):
        raise ValueError('EEPROM backup integrity mismatch')
    validate_snapshot(data)
    return data


async def backup(peer, output, password, adapter):
    async with connect(peer, adapter=adapter) as (_, identity, revision):
        if revision != '1.4.01':
            raise RuntimeError('Wireless backup requires unmodified 1.4.01; SEC002 intentionally blocks this path')
        session = Session(peer, adapter)
        try:
            first = await session.read(0, 65536, progress('Backup pass 1'))
            second = await session.read(0, 65536, progress('Backup pass 2'))
            if first != second:
                raise RuntimeError('Independent EEPROM reads differ; nothing written')
            validate_snapshot(first)
            payload = snapshot_payload(peer, identity, first)
            private.save(output, payload, password)
            return {'backup_saved': True, 'two_reads_equal': True,
                    'source_ds_sha256': digest(first[DS1:DS1 + DS_SIZE]), 'writes_sent': 0}
        finally:
            session.close()


async def check_stock(session, original):
    runtime = await session.read16(0x2044D0)
    if struct.unpack_from('<II', runtime, 4) != (0, DS1):
        raise RuntimeError('Only currently running stock SS1/DS1 is supported')
    current = await session.read(0, 65536, progress('Live preflight backup'))
    validate_snapshot(current)
    if current[:40] != original[:40] or current[DS1:DS1 + DS_SIZE] != original[DS1:DS1 + DS_SIZE]:
        raise RuntimeError('Stock/SS1 identity differs from your backup; no write sent')
    return current


async def enable(session):
    config = await session.read16(0x2008B0)
    timer = await session.read16(0x2008C0)
    driver = await session.read16(0x200DA0)
    utility = await session.read16(0x2008A0)
    spec = json.loads((Path(__file__).resolve().parent.parent / 'patches/sec002.json').read_text(encoding='utf-8'))
    rom = await session.read16(0x17470) + await session.read16(0x17480)
    if (config[:8] != bytes.fromhex('70 71 72 73 74 75 fa 00') or config[14]
            or struct.unpack_from('<H', timer)[0] != 10 or struct.unpack_from('<i', timer, 4)[0] != -1
            or driver[4] != 16
            or struct.unpack_from('<I', driver, 8)[0] != 0x16D51 or utility[11] != 255
            or digest(rom) != spec['rom_fwu_fingerprint_sha256']):
        raise RuntimeError('ROM/runtime/WP fingerprint differs; no write sent')
    session.policy.opened = True
    await session.command(b'\x70')
    await session.write(0x2008AB, b'\x01')
    if (await session.read16(0x2008A0))[11] != 1:
        raise RuntimeError('Temporary WP override did not verify')


async def restore_wp(session):
    if not session.policy.opened:
        return
    value = (await session.read16(0x2008A0))[11]
    if value != 255:
        await session.command(b'\x70')
        await session.write(0x2008AB, b'\xff')
    if (await session.read16(0x2008A0))[11] != 255:
        raise RuntimeError('Could not verify WP restoration; let the watchdog reset the lock')


async def write_checked(session, offset, data, notify=None):
    if not data or not 0 <= offset < offset + len(data) <= 65536:
        raise ValueError('Invalid EEPROM write range')
    for page in range(offset & ~15, (offset + len(data) + 15) & ~15, 16):
        current = await session.read(page, 16)
        expected = bytearray(current)
        start, end = max(offset, page), min(offset + len(data), page + 16)
        expected[start - page:end - page] = data[start - offset:end - offset]
        for cursor in range(start, end, 11):
            size = min(11, end - cursor)
            part = bytes(expected[cursor - page:cursor - page + size])
            if current[cursor - page:cursor - page + size] != part:
                await session.write(BASE + cursor, part)
        if await session.read(page, 16) != expected:
            raise RuntimeError(f'Page readback failed at {page:#x}; write not retried')
        if notify:
            notify(end - offset, len(data))


async def stage_image(session, image, current):
    await write_checked(session, DS2, image.candidate, progress('Stage/check DS2 pages'))
    after = await session.read(0, 65536, progress('Full post-stage verification'))
    expected = bytearray(current)
    expected[DS2:DS2 + len(image.candidate)] = image.candidate
    if after != expected:
        raise RuntimeError('Post-stage full EEPROM differs from the exact expected image')
    return after


async def activate_image(session, image):
    if await session.read(DS2, len(image.candidate), progress('Recheck staged SEC002')) != image.candidate:
        raise RuntimeError('DS2 is not the fixed SEC002; selectors not changed')
    await write_checked(session, 0x100, image.new_ss2)
    if await session.read(0x100, 40) != image.new_ss2:
        raise RuntimeError('New SS2 did not verify')
    session.policy.ss2_verified = True
    await write_checked(session, 0, b'\0')
    if await session.read(0, 40) != b'\0' + image.ss1[1:]:
        raise RuntimeError('SS1 commit did not verify')


async def recover_selector(session, image):
    """Best effort while the same link still works; not a boot rollback."""
    value = await session.read(0, 40)
    if value[1:] != image.ss1[1:]:
        raise RuntimeError('Unexpected SS1 body; refused recovery write')
    if value != image.ss1:
        session.policy.recovery = True
        await session.command(b'\x70')
        await session.write(0x2008AB, b'\x01')
        await write_checked(session, 0, b'\x01')
    return await session.read(0, 40) == image.ss1


async def verify(peer, identity, adapter):
    async with connect(peer, identity, adapter) as (client, _, revision):
        if revision != 'SEC002':
            raise RuntimeError('The device has not reported SEC002')
        session = Session(peer, adapter)
        try:
            setup = b'\x71' + struct.pack('<IH', 0, 16)
            from .radio import checksum
            try:
                await session.command(setup + bytes([checksum(setup)]))
            except TimeoutError:
                denied = True
            else:
                raise RuntimeError('Raw FWU still answers; hardening check failed')
        finally:
            session.close()
        if bytes(await client.read_gatt_char(REVISION)).rstrip(b'\0') != b'SEC002':
            raise RuntimeError('GATT stopped responding after the read-only denial probe')
        return {'firmware': revision, 'raw_read_setup_no_reply': denied,
                'gatt_alive_after_probe': True, 'owner_authentication_tested': False}


async def change(phase, payload, backup_path, password, adapter):
    original = snapshot_data(payload)
    image = plan(original)
    peer, identity = payload['address'], payload['identity']
    report = {'phase': phase, 'candidate_sha256': digest(image.candidate), 'write_retries': 0,
              'stock_ds1_preserved': False, 'owner_storage_written': False,
              'boot_verified': False, 'wireless_sec002_end_to_end_hardware_qualification': 'experimental'}
    stamp = datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')
    base = Path(backup_path)
    receipt = base.parent / f'{phase}-{stamp}.receipt.json'

    def journal():
        receipt.write_text(json.dumps(report, indent=2), encoding='utf-8')
        receipt.chmod(0o600)
        private.invoking_owner(receipt)

    journal()
    try:
        async with connect(peer, identity, adapter) as (_, _, revision):
            if revision != '1.4.01':
                raise RuntimeError('Install requires unmodified 1.4.01; SEC002 updates need UART')
            policy = WritePolicy(phase, image)
            session = Session(peer, adapter, policy)
            try:
                current = await check_stock(session, original)
                if phase == 'activate' and current[DS2:DS2 + DS_SIZE] != image.candidate:
                    raise RuntimeError('Stage SEC002 first; no write sent')
                private.save(base.parent / f'{phase}-{stamp}.before.qsb', snapshot_payload(peer, identity, current), password)
                report['live_before_backup_saved'] = True
                journal()
                try:
                    await enable(session)
                    if phase == 'stage':
                        after = await stage_image(session, image, current)
                        private.save(base.parent / f'{phase}-{stamp}.after.qsb', snapshot_payload(peer, identity, after), password)
                        report['full_stage_readback_verified'] = True
                    else:
                        await activate_image(session, image)
                        report['selectors_readback_verified'] = True
                    report['stock_ds1_preserved'] = True
                except (Exception, asyncio.CancelledError):
                    if phase == 'activate' and policy.opened:
                        try:
                            report['pre_boot_selector_recovery_verified'] = await recover_selector(session, image)
                        except Exception as error:
                            report['selector_recovery_error_type'] = type(error).__name__
                    raise
                finally:
                    await restore_wp(session)
                    report['temporary_wp_restored'] = True
                    report['write_attempts'] = session.write_attempts
                    journal()
            finally:
                session.close()
        print('Waiting 13 seconds for the stock FWU watchdog reboot.', flush=True)
        await asyncio.sleep(13)
        if phase == 'activate':
            report['boot_check'] = await verify(peer, identity, adapter)
            report['boot_verified'] = True
        else:
            async with connect(peer, identity, adapter) as (_, _, revision):
                if revision != '1.4.01':
                    raise RuntimeError('Expected unchanged stock boot after staging')
                report['stock_boot_after_stage_verified'] = True
        report['completed'] = True
        journal()
        return report
    except (Exception, asyncio.CancelledError) as error:
        report['stopped'] = type(error).__name__
        report['automatic_boot_rollback'] = False
        journal()
        raise
