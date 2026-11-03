# Q-SL1 LAN relay with XIAO ESP32C3

[日本語](README.ja.md) | English

This guide sets up operation through a XIAO near the door. See the [project overview](../README.en.md) for requirements and qualification.

## What it provides

- Lock/unlock from a Pi farther away through the LAN and XIAO.
- Owner private keys on the Pi; Bluetooth handled by the XIAO.
- Authenticated status checks before enabling MQTT/HomeKit service operation.

```text
Apple Home -> Home Assistant / MQTT -> Raspberry Pi
                                           | encrypted LAN
                                      XIAO ESP32C3
                                           | BLE
                                         Q-SL1
```

The XIAO uses USB power and connects wirelessly to the Q-SL1. Its USB flashing is independent of lock firmware updates.

**One owned unit passed relay authentication/status; the user confirmed Home app locking with the Pi farther away, correlated with normal motor completion.** Other units, long-term operation and a complete fresh installation are unverified. This does not qualify the SEC002 wireless installer.

## Prerequisites

| Category | Required |
| --- | --- |
| Lock | Your Q-SL1, working batteries, **registered `owner.json` operation credentials** |
| Relay | Seeed Studio XIAO ESP32C3, compatible external 2.4 GHz antenna, USB power |
| Initial upload | USB data cable and Python 3.12+ build PC |
| Operation host | Pi/Linux with Python 3.11+ |
| LAN | Home 2.4 GHz Wi-Fi, Pi/XIAO communication, DHCP reservation |
| Optional HomeKit | iPhone, existing Home Assistant and authenticated MQTT broker |

If credentials are missing, use [card enrollment or existing-vault export](../onboarding/README.en.md). Fresh enrollment also requires the supported locally supplied archived APK and is not hardware-tested end to end. For enrollment through the XIAO, steps 1–3 and relay configuration export below can be completed first without owner credentials. Operation authentication fields are `lock_uuid`, `phone_uuid`, `signing_private_pem`, `mq_public`, `challenge_a`, and `challenge_b`.

Command-line operation needs no Home Assistant, MQTT or iPhone. The included `qrio_protocol.py` handles framing/authentication without APK/SDK dependencies at runtime.

## Setup order

1. Obtain source and create a build environment.
2. Configure Wi-Fi and a private API key locally.
3. Build/upload XIAO firmware and verify encrypted LAN connectivity.
4. Verify authenticated status and actual locking from the Pi.
5. Configure the service and HomeKit if wanted.

## 1. Source and environment

The old v0.1.0 ZIP excludes the relay; use current source.

```sh
git clone https://github.com/bruiselea/qrio-sec002.git
cd qrio-sec002
```

Windows build environment; keep it separate from the Pi runtime because ESPHome uses a different MQTT library version:

```powershell
python -m venv .venv-firmware
.venv-firmware\Scripts\python -m pip install -r relay\requirements-build.txt
```

## 2. Generate private Wi-Fi and key configuration

```powershell
.venv-firmware\Scripts\python relay\prepare.py --output "$env:USERPROFILE\.qrio-sl1\relay-xiao"
```

Enter SSID and the hidden Wi-Fi password locally. The tool generates a random 32-byte API key and refuses an existing output directory. On Linux, use a private path such as `~/.qrio-sl1/relay-xiao`.

This directory contains `secrets.yaml` and configuration copies. Generated firmware also embeds Wi-Fi credentials and the API key: do not commit or distribute the directory or firmware. `--demo` only prepares synthetic configuration for compilation checks.

## 3. Build and upload to the XIAO

Attach the compatible external antenna while power is disconnected, then connect the XIAO to the PC by USB. Do not wire it to Q-SL1 UART/power pins.

```powershell
.venv-firmware\Scripts\python -m serial.tools.list_ports
.venv-firmware\Scripts\python -m esptool --port COM_PORT read-mac
.venv-firmware\Scripts\python relay\build.py --config "$env:USERPROFILE\.qrio-sl1\relay-xiao\xiao-esp32c3.yaml"
.venv-firmware\Scripts\python relay\build.py --action upload --device COM_PORT --config "$env:USERPROFILE\.qrio-sl1\relay-xiao\xiao-esp32c3.yaml"
```

Replace `COM_PORT` with the actual XIAO port and record its Wi-Fi MAC privately. Do not confuse it with a separate C3 UART adapter. The upload changes the XIAO, not the Q-SL1 firmware. Back up any XIAO program you need before replacement.

`build.py` clears unrelated IDF environment variables only in its child process. On Windows it keeps downloads and temporary files on the same volume. First compilation downloads ESP-IDF/toolchains and can take time. See [Seeed's antenna/Wi-Fi guide](https://wiki.seeedstudio.com/XIAO_ESP32C3_WiFi_Usage/).

## 4. Verify encrypted LAN access

Once the flashed XIAO is on Wi-Fi:

```powershell
.venv-firmware\Scripts\python relay\export_gateway_config.py --build-dir "$env:USERPROFILE\.qrio-sl1\relay-xiao" --mac 00:11:22:33:44:55 --output "$env:USERPROFILE\.qrio-sl1\relay-xiao\relay.private.json"
```

The shown MAC is synthetic; replace it with the **XIAO Wi-Fi MAC** recorded over USB. If mDNS fails, add `--host` with the XIAO's IPv4 address. Successful encrypted API authentication and relay identity verification save the private host configuration. This check does not connect to the lock.

Reserve that address in your router's DHCP configuration. An address change requires updating both the private `host` field and the systemd allow rule.

## 5. Check the relay from the Pi

Obtain source on the Pi and create its runtime environment:

```sh
python3 -m venv .venv-relay
.venv-relay/bin/python -m pip install -r relay/requirements-runtime.txt
.venv-relay/bin/python relay/verify.py
```

Transfer your `relay.private.json` and `owner.json` over your own SSH/SCP connection into a private directory. Protect it first. Replace `YOUR_USER@YOUR_PI` with your host:

```powershell
ssh YOUR_USER@YOUR_PI "install -d -m 700 .config/qrio-relay"
scp "$env:USERPROFILE\.qrio-sl1\relay-xiao\relay.private.json" YOUR_USER@YOUR_PI:.config/qrio-relay/relay.private.json
ssh YOUR_USER@YOUR_PI "chmod 600 .config/qrio-relay/relay.private.json"
```

Protect your owner file similarly and retain existing working keys rather than overwriting them.

```sh
chmod 600 ~/.config/qrio-relay/owner.json
.venv-relay/bin/python relay/qrio_live.py status \
  --credential ~/.config/qrio-relay/owner.json \
  --relay-config ~/.config/qrio-relay/relay.private.json --reset-pairing
```

Power the XIAO on the indoor side about 30 cm–1 m from the lock. Keep the antenna away from direct metal-door contact and within Wi-Fi range. Stop an existing gateway during standalone diagnostics to avoid concurrent connections.

`authenticated: true` with `settings_fields` means authentication/read succeeded. These fields do not prove the physical lock position. Without `--relay-config`, the command uses host Bluetooth instead; specify it when testing the relay.

For a deliberate physical test, check the lock's circumstances yourself, replace `status` with `lock`, run once, and verify the response and actual locking. `unlock` releases the lock. Motor commands are not automatically replayed.

## 6. Service and HomeKit

Follow [systemd and HomeKit](SYSTEMD_HOMEKIT.en.md). `qrio_home_daemon.py` publishes MQTT Discovery for `lock.qrio_sl1`, which Home Assistant's HomeKit Bridge exposes to the iPhone. Retain existing HomeKit pairing when available.

State expires to unknown 30 seconds after normal motor completion. Manual knob tracking is unsupported. A communication failure is not treated as success, and operations are not replayed.

## Implementation, evidence and distribution

- [Testing scope](TESTING.en.md).
- [Sources, prior research and dependencies](../SOURCES.en.md).
- [ESPHome Bluetooth proxy](https://esphome.io/components/bluetooth_proxy/) and [encrypted API](https://esphome.io/components/api/).
- Original project source/configuration/docs use the [MIT License](LICENSE). Dependencies retain their own licenses.

Owner private keys stay on the Pi. LAN transport uses Noise encryption with a random key; XIAO OTA is also authenticated/encrypted with that key. A key holder can use ESPHome's generic Bluetooth proxy. The adapter's GATT restrictions do not restrict the entire ESPHome device to Q-SL1 traffic. Protect the API key.
