"""Offline pipe/process checks for timely completion and exclusive BLE cleanup."""

import asyncio
import json
from pathlib import Path
import signal
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from qrio_home_daemon import Bridge, valid_worker_success, reap_worker, discard_stream

KILL_SIGNAL = getattr(signal, 'SIGKILL', 9)


class Child:
    def __init__(self, result=None, finished=False):
        self.stdout, self.stderr = asyncio.StreamReader(), asyncio.StreamReader()
        self.returncode = None
        self.done = asyncio.Event()
        self.signals = []
        if result is not None:
            self.stdout.feed_data(json.dumps(result).encode() + b'\n')
        if finished:
            self.finish(0 if result and result.get('authenticated') else 1)

    def finish(self, code=0):
        if self.returncode is None:
            self.returncode = code
            self.stdout.feed_eof()
            self.stderr.feed_eof()
            self.done.set()

    async def wait(self):
        await self.done.wait()
        return self.returncode

    def kill(self):
        self.signals.append(KILL_SIGNAL)
        self.finish(-9)

    def send_signal(self, value):
        self.signals.append(value)
        self.finish(-int(value))


def bridge():
    with patch('qrio_home_daemon.mqtt.Client'):
        item = Bridge({'credential_path': '/synthetic'}, {'username': 'test', 'password': 'synthetic'}, Path('.'))
    item.loop = asyncio.get_running_loop()
    return item


async def main():
    motor = {'authenticated': True, 'action': 'lock', 'result_fields': [0, 0, 4, 4]}
    status = {'authenticated': True, 'settings_fields': [0, 0, 4, 4, 0, 0, 0]}
    assert valid_worker_success(motor, 'lock') and valid_worker_success(status, 'status')
    for item in [dict(motor, action='unlock'), dict(motor, result_fields=[]),
                 dict(motor, result_fields=[True, 0]), dict(motor, authenticated=False)]:
        assert not valid_worker_success(item, 'lock')
    first, second = Child(motor), Child(status)
    spawned = []

    async def spawn(*args, **kwargs):
        child = (first, second)[len(spawned)]
        spawned.append(child)
        return child

    b = bridge()
    with patch('qrio_home_daemon.asyncio.create_subprocess_exec', side_effect=spawn):
        assert await asyncio.wait_for(b.worker('lock'), 0.2) == motor
        assert first.returncode is None  # Publish before disconnect/exit.
        waiting = asyncio.create_task(b.worker('status'))
        await asyncio.sleep(0.02)
        assert len(spawned) == 1 and not waiting.done()  # Never overlap BLE.
        first.finish()
        assert await asyncio.wait_for(waiting, 0.2) == status
        second.finish()
        await b._worker_cleanup
    # A malformed authenticated result cannot cause a second motor attempt.
    bad = Child(dict(motor, action='unlock'), finished=True)
    b = bridge()
    with patch('qrio_home_daemon.asyncio.create_subprocess_exec', return_value=bad) as spawn_mock:
        try:
            await b.worker('lock')
        except RuntimeError:
            pass
        else:
            raise AssertionError('Accepted the wrong action acknowledgement')
        assert spawn_mock.call_count == 1
    # Cancelling only the poll stops its child before a real command proceeds.
    b, child = bridge(), Child()
    b.save = lambda *args: None
    b.publish = lambda *args: None
    with patch('qrio_home_daemon.asyncio.create_subprocess_exec', return_value=child) as spawn_mock:
        poll = asyncio.create_task(b.poll_with_command_priority())
        await asyncio.sleep(0.02)
        b.on_message(None, None, SimpleNamespace(payload=b'LOCK', retain=False, dup=False))
        await asyncio.wait_for(poll, 0.2)
        assert child.returncode is not None and child.signals == [signal.SIGINT]
        assert spawn_mock.call_count == 1 and (await b.commands.get())[0] == 'LOCK'
    # Connection failures may retry before actuation; valid motor error replies
    # still return once, for motor_success() to mark JAMMED without replay.
    failed = Child({'stage': 'connecting', 'error_type': 'BleakError'}, finished=True)
    good = Child(status, finished=True)
    b = bridge()
    with patch('qrio_home_daemon.asyncio.create_subprocess_exec', side_effect=[failed, good]) as spawn_mock:
        assert await b.worker('status') == status
        assert spawn_mock.call_count == 2
        await b._worker_cleanup
    jam = Child(dict(motor, result_fields=[0, 1, 0, 0]), finished=True)
    b = bridge()
    with patch('qrio_home_daemon.asyncio.create_subprocess_exec', return_value=jam) as spawn_mock:
        result = await b.worker('lock')
        assert result['result_fields'][1] == 1 and spawn_mock.call_count == 1
        await b._worker_cleanup
    # An ambiguous motor timeout must kill its worker and never replay it.
    b, child = bridge(), Child()
    original_timeout = asyncio.timeout
    with patch('qrio_home_daemon.asyncio.create_subprocess_exec', return_value=child) as spawn_mock, \
         patch('qrio_home_daemon.asyncio.timeout', side_effect=lambda _: original_timeout(0.02)):
        try:
            await b.worker('lock')
        except RuntimeError:
            pass
        else:
            raise AssertionError('A missing motor result was accepted')
        assert spawn_mock.call_count == 1 and child.signals == [KILL_SIGNAL]
    child = Child()
    await reap_worker(child, asyncio.create_task(discard_stream(child.stderr)), timeout=0.02)
    assert child.returncode is not None and child.signals == [KILL_SIGNAL]
    b = bridge()
    b.commands.put_nowait(('LOCK', 0))
    b.command_pending.set()
    b.poll = AsyncMock()
    await b.poll_with_command_priority()
    b.poll.assert_not_awaited()
    print('Worker latency checks passed: result precedes child exit; next BLE worker waits for cleanup; malformed/motor-error results never replay; read-only poll cancellation preserves queued command; safe pre-connection retry retained.')


if __name__ == '__main__':
    asyncio.run(main())
