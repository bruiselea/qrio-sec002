"""Synthetic checks of lock completion, retained messages and command admission."""

import asyncio
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from qrio_home_daemon import Bridge, discovery, motor_success, safe_connection_retry


async def main():
    assert motor_success(bytes([0, 0, 0, 0]))
    assert motor_success(bytes([1, 0, 0, 4]))  # Successful motion with spare-bank warning.
    assert not motor_success(bytes([0, 1, 0, 0]))
    assert not motor_success(b"")
    assert safe_connection_retry({"stage": "connecting", "error_type": "BleakError"})
    assert not safe_connection_retry({"stage": "actuating", "error_type": "TimeoutError"})
    assert not safe_connection_retry({"authenticated": True, "stage": "connecting"})
    config = discovery()
    assert not config["optimistic"] and not config["retain"]
    assert config["default_entity_id"] == "lock.qrio_sl1"
    with patch("qrio_home_daemon.mqtt.Client"):
        bridge = Bridge({}, {"username": "test", "password": "synthetic"}, Path("."))
    bridge.loop = asyncio.get_running_loop()
    assert bridge.state == "None"
    for message in (SimpleNamespace(payload=b"UNLOCK", retain=True, dup=False),
                    SimpleNamespace(payload=b"UNLOCK", retain=False, dup=True),
                    SimpleNamespace(payload=b"other", retain=False, dup=False)):
        bridge.on_message(None, None, message)
    await asyncio.sleep(0)
    assert bridge.commands.empty()
    # A settings poll provides no lock-position evidence. It must not renew a
    # previous motor result or restore it after the freshness deadline.
    messages = []
    bridge.publish = lambda topic, value: messages.append((topic, value))
    bridge.save = lambda *args: None
    async def worker(action):
        return {"result_fields": [0, 0, 4, 4], "settings_fields": [0, 0, 4, 4, 0, 0, 0]}
    bridge.worker = worker
    with patch("qrio_home_daemon.time.monotonic", return_value=100):
        await bridge.actuate("LOCK")
    with patch("qrio_home_daemon.time.monotonic", return_value=129):
        await bridge.poll()
        assert bridge.state == "LOCKED" and not bridge.expire_state()
    with patch("qrio_home_daemon.time.monotonic", return_value=130):
        assert bridge.expire_state()
    assert bridge.state == "None" and messages[-2][1] == "None"
    assert bridge.attributes["last_completed_state"] == "LOCKED"
    await bridge.poll()
    assert bridge.state == "None" and bridge.attributes["state_expired"]
    valid = SimpleNamespace(payload=b"LOCK", retain=False, dup=False)
    bridge.on_message(None, None, valid)
    await asyncio.sleep(0)
    assert (await bridge.commands.get())[0] == "LOCK"
    bridge.busy = True
    bridge.on_message(None, None, valid)
    await asyncio.sleep(0)
    assert bridge.commands.empty()
    print("Completion handling, 30-second state expiry without renewal by settings polling, unknown startup state, non-optimistic discovery and stale/duplicate/busy command rejection passed.")


if __name__ == "__main__":
    asyncio.run(main())
