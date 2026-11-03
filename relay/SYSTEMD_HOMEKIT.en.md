# systemd service and Apple's Home app

[日本語](SYSTEMD_HOMEKIT.ja.md) | English

For Linux/Pi OS with systemd encrypted credentials. Start after [standalone authenticated relay status](README.en.md) succeeds and Home Assistant plus an authenticated MQTT broker already run on the Pi. See [owner enrollment/vault export](../onboarding/README.en.md) for keys. Broker and Home Assistant installers are not included.

## Runtime files and environment

Install source as root-owned files and keep secrets outside it. This example uses a new `/opt/qrio-relay`. If it already exists, back up the current installation before updating.

```sh
sudo install -d -m 755 /opt/qrio-relay
sudo install -m 644 relay/qrio_protocol.py relay/qrio_live.py relay/qrio_esphome_transport.py relay/qrio_home_daemon.py relay/bluez_qrio_agent.py relay/requirements-runtime.txt /opt/qrio-relay/
sudo python3 -m venv /opt/qrio-relay/.venv
sudo /opt/qrio-relay/.venv/bin/python -m pip install -r /opt/qrio-relay/requirements-runtime.txt
```

Create the system account only if `qrio-sl1` does not already exist:

```sh
sudo useradd --system --home-dir /nonexistent --shell /usr/sbin/nologin qrio-sl1
```

## Encrypted credentials

Copy `mqtt.example.json` into private storage and edit it with your broker username/password. This example connects to `127.0.0.1:1883` on the Pi. Disable anonymous access and set appropriate permissions for `qrio/sl1/#` and the necessary Discovery topics on your own broker.

Keep `owner.json`, `mqtt.private.json`, and `relay.private.json` private with mode 600. Encrypt them for systemd without placing secret values in command arguments:

```sh
sudo install -d -m 700 /etc/credstore.encrypted
sudo systemd-creds encrypt --name=owner.json ~/.config/qrio-relay/owner.json /etc/credstore.encrypted/qrio-relay-owner.cred
sudo systemd-creds encrypt --name=mqtt.json ~/.config/qrio-relay/mqtt.private.json /etc/credstore.encrypted/qrio-relay-mqtt.cred
sudo systemd-creds encrypt --name=relay.json ~/.config/qrio-relay/relay.private.json /etc/credstore.encrypted/qrio-relay-api.cred
```

If an output already exists, retain existing keys and plan a separately named update. On an OS without `systemd-creds`, do not substitute plaintext secrets in the service file.

## Service installation

Edit your local `qrio-relay.service.example` first. Replace its `IPAddressAllow=192.168.1.123/32` with the reserved XIAO address; do not embed keys.

```sh
sudo install -m 644 relay/qrio-relay.service.example /etc/systemd/system/qrio-relay.service
sudo systemctl daemon-reload
sudo systemctl enable --now qrio-relay.service
sudo systemctl status qrio-relay.service --no-pager
sudo cat /var/lib/qrio-sl1-gateway/bridge-status.json
```

Retain `IPAddressDeny=any`, allowing only localhost and the XIAO. Stop any other gateway operating the same lock before starting this one. Do not run two competing gateways.

## Migrating an existing gateway

Retain owner/MQTT credentials, HomeKit pairing and the Home Assistant entity. Install the new runtime in a separate directory/venv, then check standalone `status --relay-config ...`.

Stop the existing service. Point ExecStart at the new `qrio_home_daemon.py`; add `LoadCredentialEncrypted=relay.json:...`, `QRIO_RELAY_CONFIG`, and the XIAO IP allow rule. The actual credential mount path depends on the **service name**. Adapt `/run/credentials/YOUR_SERVICE.service/relay.json` accordingly.

Do not re-enroll the owner key or reset HomeKit pairing. If migration fails, stop the service, restore the saved ExecStart/settings, place the Pi near the lock, and resume the previous direct-BLE configuration. Save service files and source before the change.

## Home Assistant and iPhone

1. In Home Assistant's Settings → Devices & services, configure MQTT with the same authenticated broker used by the gateway.
2. MQTT Discovery normally creates `lock.qrio_sl1`. Check the actual entity ID if one already exists.
3. Expose only this entity through HomeKit Bridge. The demonstrated configuration uses `accessory` mode. See the [official manual configuration](https://www.home-assistant.io/integrations/homekit/) for options not exposed by the UI.
4. Put the iPhone on the same LAN and scan the pairing QR displayed locally by Home Assistant in Apple's Home app. Retain existing pairing rather than adding again.
5. Leave the XIAO powered near the door, move the Pi farther away, and deliberately confirm one actual lock operation yourself.

Example for a new YAML-based HomeKit exposure; do not duplicate an existing UI configuration:

```yaml
homekit:
  - name: Qrio Home Relay
    port: 21064
    mode: accessory
    filter:
      include_entities:
        - lock.qrio_sl1
```

HomeKit uses LAN mDNS and HAP traffic. If a firewall blocks it, permit UDP 5353 and the chosen HomeKit TCP port only from the required LAN. Do not disable the full guard. Remote access needs additional infrastructure such as an Apple home hub.

The implementation reports state for at most 30 seconds after successful motor completion. It does not infer physical position from ReadStatus battery/settings fields. Manual knob tracking is unsupported.

References: [Home Assistant MQTT](https://www.home-assistant.io/integrations/mqtt/) and [HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/).
