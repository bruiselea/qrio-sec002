"""Authenticated Q-SL1 to local MQTT/HomeKit bridge.

Commands are never retained or retried after actuation. A motor completion is
shown for at most 30 seconds, then becomes unknown because manual-thumbturn
tracking is not implemented. Polling settings must never renew that state.
"""

import asyncio
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import signal
import time
import sys

import paho.mqtt.client as mqtt

ROOT = "qrio/sl1"
DISCOVERY = "homeassistant/lock/qrio_sl1/config"
STATE_VALID_SECONDS = 30


def discovery():
    return {"name": "Qrio SL1", "unique_id": "qrio_sl1_owner_bridge",
            "default_entity_id": "lock.qrio_sl1", "command_topic": ROOT + "/set",
            "state_topic": ROOT + "/state", "availability_topic": ROOT + "/availability",
            "json_attributes_topic": ROOT + "/attributes", "payload_lock": "LOCK",
            "payload_unlock": "UNLOCK", "state_locked": "LOCKED", "state_unlocked": "UNLOCKED",
            "state_locking": "LOCKING", "state_unlocking": "UNLOCKING", "state_jammed": "JAMMED",
            "optimistic": False, "retain": False, "qos": 1,
            "device": {"identifiers": ["qrio_sl1_owner_bridge"], "manufacturer": "Qrio",
                       "model": "Q-SL1", "name": "Qrio Q-SL1"}}


def motor_success(result):
    return len(result) >= 2 and result[0] in (0, 1) and result[1] == 0


def safe_connection_retry(result):
    return not result.get("authenticated") and result.get("stage") in (
        "scanning", "refreshing_pairing", "connecting", "subscribing")


def valid_worker_success(result, action):
    if result.get("authenticated") is not True:
        return False
    field = "settings_fields" if action == "status" else "result_fields"
    fields = result.get(field)
    if (not isinstance(fields, list) or len(fields) < (6 if action == "status" else 2)
            or not all(type(value) is int and 0 <= value <= 255 for value in fields)):
        return False
    return action == "status" or result.get("action") == action


async def discard_stream(stream):
    while await stream.read(4096):
        pass


async def reap_worker(process, stderr_task, timeout=10):
    """Complete disconnect in the background; drain output without logging it."""
    pending = [asyncio.create_task(discard_stream(process.stdout)), stderr_task,
               asyncio.create_task(process.wait())]
    try:
        await asyncio.wait_for(asyncio.gather(*pending), timeout)
    except (TimeoutError, asyncio.CancelledError) as error:
        if process.returncode is None:
            try:
                process.kill()
            except ProcessLookupError:
                pass
        await process.wait()
        for task in pending:
            if not task.done():
                task.cancel()
        await asyncio.gather(*pending, return_exceptions=True)
        if isinstance(error, asyncio.CancelledError):
            raise
    return process.returncode


class Bridge:
    def __init__(self, owner, settings, state_dir):
        self.owner = owner
        self.settings = settings
        self.state_dir = state_dir
        self.commands = asyncio.Queue(maxsize=1)
        self.command_pending = asyncio.Event()
        self.connected = asyncio.Event()
        self.busy = False
        self.state = "None"
        self.state_expires_at = None
        self._worker_cleanup = None
        self.attributes = {"state_source": "last_completed_motor_action", "manual_turn_tracking": False,
                           "state_valid_seconds": STATE_VALID_SECONDS, "state_expired": True}
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id="qrio-sl1-bridge", clean_session=True)
        self.client.username_pw_set(settings["username"], settings["password"])
        self.client.will_set(ROOT + "/availability", "offline", qos=1, retain=True)
        self.client.on_connect = self.on_connect
        self.client.on_message = self.on_message
        self.client.on_disconnect = self.on_disconnect

    def publish(self, suffix, payload):
        self.client.publish(ROOT + "/" + suffix, payload, qos=1, retain=True)

    def save(self, stage, error_type=None):
        report = {"stage": stage, "reported_state": self.state, **self.attributes}
        if error_type:
            report["error_type"] = error_type
        path = self.state_dir / "bridge-status.json"
        path.write_text(json.dumps(report) + "\n")
        print(stage, flush=True)

    def on_connect(self, client, userdata, flags, reason, properties):
        if reason.is_failure:
            return
        client.publish(DISCOVERY, json.dumps(discovery()), qos=1, retain=True)
        client.subscribe(ROOT + "/set", qos=1)
        client.publish(ROOT + "/state", "None", qos=1, retain=True)
        client.publish(ROOT + "/availability", "offline", qos=1, retain=True)
        self.loop.call_soon_threadsafe(self.connected.set)

    def on_disconnect(self, client, userdata, flags, reason, properties):
        self.loop.call_soon_threadsafe(self.connected.clear)

    def on_message(self, client, userdata, message):
        if message.retain or message.dup:
            return
        if message.payload not in (b"LOCK", b"UNLOCK"):
            return
        action = message.payload.decode()
        def enqueue():
            if not self.busy and self.commands.empty():
                self.commands.put_nowait((action, time.monotonic()))
                self.command_pending.set()
        self.loop.call_soon_threadsafe(enqueue)

    async def poll(self):
        result = await self.worker("status")
        fields = result["settings_fields"]
        self.attributes.update({"battery_a_code": fields[2], "battery_b_code": fields[3]})
        self.publish("availability", "online")
        self.publish("attributes", json.dumps(self.attributes))
        self.save("connected")

    async def poll_with_command_priority(self):
        """Cancel a read-only settings poll when an actual command arrives."""
        if not self.commands.empty():
            return
        poll = asyncio.create_task(self.poll())
        wake = asyncio.create_task(self.command_pending.wait())
        try:
            await asyncio.wait((poll, wake), return_when=asyncio.FIRST_COMPLETED)
            if wake.done() and not poll.done():
                poll.cancel()
                await asyncio.gather(poll, return_exceptions=True)
            else:
                await poll
        finally:
            for task in (poll, wake):
                if not task.done():
                    task.cancel()
            await asyncio.gather(poll, wake, return_exceptions=True)

    async def actuate(self, action):
        self.state = "LOCKING" if action == "LOCK" else "UNLOCKING"
        self.state_expires_at = None
        self.publish("state", self.state)
        self.save("motor_action_requested")
        reply = await self.worker("lock" if action == "LOCK" else "unlock")
        result = reply["result_fields"]
        if not motor_success(result):
            self.state = "JAMMED"
            self.publish("state", "JAMMED")
            self.save("motor_reported_failure")
            return
        self.state = "LOCKED" if action == "LOCK" else "UNLOCKED"
        self.state_expires_at = time.monotonic() + STATE_VALID_SECONDS
        self.attributes.update({"last_completed_at": datetime.now(timezone.utc).isoformat(),
                                "last_completed_state": self.state, "state_expired": False,
                                "battery_warning": bool(result[0]),
                                "battery_a_code": result[2] if len(result) >= 4 else -1,
                                "battery_b_code": result[3] if len(result) >= 4 else -1})
        self.publish("state", self.state)
        self.publish("attributes", json.dumps(self.attributes))
        self.publish("availability", "online")
        self.save("motor_action_completed")

    def expire_state(self):
        if self.state_expires_at is None or time.monotonic() < self.state_expires_at:
            return False
        self.state = "None"
        self.state_expires_at = None
        self.attributes["state_expired"] = True
        self.publish("state", "None")
        self.publish("attributes", json.dumps(self.attributes))
        self.save("motor_state_expired")
        return True

    async def worker(self, action):
        # A new operation cannot overlap the prior worker's BLE disconnect.
        if self._worker_cleanup is not None:
            cleanup, self._worker_cleanup = self._worker_cleanup, None
            await cleanup
        for attempt in range(2):
            process = await asyncio.create_subprocess_exec(sys.executable,
                str(Path(__file__).with_name("qrio_live.py")), action, "--reset-pairing", "--credential",
                self.owner["credential_path"], stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.PIPE)
            stderr_task = asyncio.create_task(discard_stream(process.stderr))
            result = None
            try:
                async with asyncio.timeout(65):
                    for _ in range(32):
                        line = await process.stdout.readline()
                        if not line:
                            break
                        try:
                            item = json.loads(line)
                        except (ValueError, UnicodeDecodeError):
                            continue
                        if isinstance(item, dict):
                            result = item
                            if valid_worker_success(result, action):
                                # The lock has already supplied its result. Do
                                # not hold HomeKit's update behind disconnect.
                                self._worker_cleanup = asyncio.create_task(reap_worker(process, stderr_task))
                                return result
            except TimeoutError:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await reap_worker(process, stderr_task)
                raise RuntimeError("BLE worker timed out; motor command not replayed") from None
            except asyncio.CancelledError:
                if process.returncode is None:
                    try:
                        process.send_signal(signal.SIGINT)
                    except ProcessLookupError:
                        pass
                await reap_worker(process, stderr_task, timeout=3)
                raise
            except Exception:
                if process.returncode is None:
                    try:
                        process.kill()
                    except ProcessLookupError:
                        pass
                await reap_worker(process, stderr_task)
                raise
            await reap_worker(process, stderr_task)
            if result is not None and attempt == 0 and safe_connection_retry(result):
                self.attributes["connection_retry"] = True
                await asyncio.sleep(2)
                continue
            self.attributes["last_error_stage"] = result.get("stage", "worker") if result else "worker"
            raise RuntimeError("BLE operation failed; no motor replay")

    async def run(self):
        self.loop = asyncio.get_running_loop()
        self.client.connect(self.settings["host"], self.settings["port"], keepalive=30)
        self.client.loop_start()
        await asyncio.wait_for(self.connected.wait(), 20)
        self.publish("state", "None")
        self.publish("availability", "offline")
        self.save("starting")
        next_poll = 0
        while True:
            try:
                deadline = next_poll
                if self.state_expires_at is not None:
                    deadline = min(deadline, self.state_expires_at)
                timeout = max(0.1, deadline - time.monotonic())
                try:
                    action, received = await asyncio.wait_for(self.commands.get(), timeout)
                    if self.commands.empty():
                        self.command_pending.clear()
                except TimeoutError:
                    action = None
                if self.expire_state() and not action:
                    continue
                self.busy = bool(action)
                if action:
                    if time.monotonic() - received > 20:
                        continue
                    await self.actuate(action)
                else:
                    await self.poll_with_command_priority()
                next_poll = time.monotonic() + 60
            except Exception as error:
                self.state = "None"
                self.state_expires_at = None
                self.attributes["state_expired"] = True
                self.publish("state", "None")
                self.publish("availability", "offline")
                self.save("connection_failed", type(error).__name__)
                next_poll = time.monotonic() + 20
            finally:
                self.busy = False


async def main():
    os.umask(0o077)
    credentials = Path(os.environ["CREDENTIALS_DIRECTORY"])
    owner = {"credential_path": str(credentials / "owner.json")}
    settings = json.loads((credentials / "mqtt.json").read_text())
    await Bridge(owner, settings, Path(os.environ.get("STATE_DIRECTORY", "/var/lib/qrio-sl1-gateway"))).run()


if __name__ == "__main__":
    asyncio.run(main())
