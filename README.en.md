# Qrio Q-SL1 local control and HomeKit relay

[日本語](README.md) | English

**Release: [v0.9 (pre-release)](https://github.com/bruiselea/qrio-sec002/releases/tag/v0.9)** — complete source with enrollment, relay, wired recovery, and English guides. [ZIP](https://github.com/bruiselea/qrio-sec002/releases/download/v0.9/qrio-sec002-v0.9.zip) · [SHA-256](https://github.com/bruiselea/qrio-sec002/releases/download/v0.9/SHA256SUMS-v0.9.txt)

Code and instructions for operating the original **Qrio Smart Lock (Q-SL1)** with registered owner credentials, including control from Apple's Home app. A XIAO ESP32C3 near the door relays Bluetooth over the LAN, allowing the Raspberry Pi to stay farther away.

The repository also includes the **SEC002 firmware delta**, which closes specific maintenance interfaces. The relay and the lock firmware patch are separate features.

**[Owner registration and keys](onboarding/README.en.md)** · **[LAN relay setup](relay/README.en.md)** · **[systemd and HomeKit](relay/SYSTEMD_HOMEKIT.en.md)** · **[SEC002 firmware](README.firmware.en.md)**

**[Wired backup and recovery](wired/README.en.md)** · **[SEC001 boot failure report](docs/BOOT_FAILURE.en.md)** · **[Sources and acknowledgments](SOURCES.en.md)**

## Capabilities

| Goal | Included tools |
| --- | --- |
| Prepare owner credentials from a card | Local enrollment, an encrypted recovery vault, and export after authenticated verification; the new public enrollment workflow has not been tested end to end on hardware |
| Lock or unlock from a PC/Pi | Commands and authentication using an already registered owner key |
| Use Apple's Home app | An MQTT gateway and instructions for Home Assistant's HomeKit Bridge |
| Keep the Pi away from the door | Encrypted Wi-Fi/Bluetooth relay using a XIAO ESP32C3 |
| Keep owner authentication local | Owner private keys remain on the host/Pi |
| Close known firmware maintenance paths | The SEC002 delta, generation tools, and initial installation instructions |
| Capture and narrowly recover a nonbooting unit | Encrypted UART backups and stock boot-marker restoration when stock DS1 and SS1 remain intact |

Normal operation uses your own local devices. Internet access is needed to obtain software during setup.

## Architecture

```text
Apple Home app
      | home LAN
Home Assistant + MQTT + owner gateway on Raspberry Pi
      | encrypted LAN; XIAO uses 2.4 GHz Wi-Fi
XIAO ESP32C3 + external antenna near the door
      | Bluetooth LE
Qrio Smart Lock Q-SL1
```

The USB-powered XIAO handles Bluetooth near the lock. No wire connects it to the Q-SL1. Owner private keys stay on the Pi.

## Requirements

| Item | Purpose or condition |
| --- | --- |
| Your Q-SL1 and working batteries | Original Q-SL1 only; later models such as Q-SL2 are unsupported |
| **Registered owner credentials, `owner.json`** | An operation file containing private credentials already registered with the lock |
| A Raspberry Pi or other Linux host | Runs authentication and the gateway; Python 3.11+ |
| Seeed Studio XIAO ESP32C3 | Wi-Fi/Bluetooth relay near the door |
| Compatible external 2.4 GHz antenna | Connected to the XIAO |
| USB data cable and USB power supply | Initial XIAO flashing and continuous power near the door |
| Home 2.4 GHz Wi-Fi | Pi-to-XIAO connectivity and a DHCP reservation for the XIAO |
| Build PC | Python 3.12+ for the XIAO build; Windows examples are provided |

**If you do not have operation credentials, start with [owner enrollment or an existing vault](onboarding/README.en.md).** New enrollment requires your owner card and a locally supplied archived APK with the supported 1.8.7 library. The APK and coefficient table are not bundled. An existing encrypted vault can be verified and exported without the APK. The public enrollment workflow has not been tested end to end on hardware.

To use Apple's Home app, also provide an iPhone, an existing Home Assistant installation, an authenticated MQTT broker, and HomeKit Bridge configuration. Initial pairing requires the iPhone on the same LAN. Installers for Home Assistant and the broker are not included. Command-line control does not require them or an iPhone. Remote Home access needs additional infrastructure such as an Apple home hub.

## Where to start

### Home app or LAN relay

1. Prepare a registered `owner.json` using [enrollment or vault export](onboarding/README.en.md), or retain your existing working credentials.
2. Obtain the latest repository source.
3. Provision Wi-Fi and relay firmware on the XIAO.
4. Verify authenticated status through the relay from the Pi.
5. Confirm an actual lock operation, then configure the service, MQTT, and HomeKit.

```sh
git clone https://github.com/bruiselea/qrio-sec002.git
cd qrio-sec002
```

Continue with the **[XIAO relay guide](relay/README.en.md)**. Its flashing steps target the XIAO. Installing SEC002 on the lock is a separate decision. Relay hardware testing used one Q-SL1 already running SEC002.

### SEC002 firmware protection

Read the [firmware overview](README.firmware.en.md), [initial wireless installation](docs/WIRELESS_INSTALL.en.md), and [recovery limits](docs/RECOVERY.en.md). Only the known stock 1.4.01 DS1 hash and layout are supported.

**The public stock-to-SEC002 wireless installation workflow is experimental and has not been tested end to end on hardware.** SEC002 closes wireless update interfaces. Later firmware maintenance and recovery from boot failure require UART. There is no automatic boot rollback. The [wired kit](wired/README.en.md) only restores the boot marker when a same-unit known-good backup is available and stock DS1/SS1 remain intact; its new public recovery CLI is also not hardware-qualified end to end.

### Wired inspection or recovery

The [wired guide](wired/README.en.md) covers equipment, F9/F10/F11 wiring, the C3 UART bridge, and independent encrypted captures. Recovery defaults to an offline plan and requires explicit execution. The [incident report](docs/BOOT_FAILURE.en.md) distinguishes observations, possible causes, and unresolved questions about SEC001.

## Evidence and limitations

| Item | Status |
| --- | --- |
| XIAO LAN relay | Owner authentication and status succeeded on one owned unit |
| Home app locking | User confirmed locking with the Pi farther away; correlated with normal motor completion records |
| Public relay runtime | 13 synthetic tests passed on Windows and the Pi |
| Public enrollment/vault | 29 synthetic tests passed on Windows and the Pi; fresh enrollment not tested end to end on hardware |
| Public wired kit | 27 tests passed on Windows; 26 passed and one Windows-only test skipped on Pi; C3 build succeeded; public recovery CLI not tested end to end on hardware |
| SEC002 firmware | UART deployment, boot, and rejection of known paths checked on the same unit |
| Public all-wireless SEC002 installation | No end-to-end hardware test |
| Other units, long-term use, complete fresh installation | Not verified |

The reported lock state expires to unknown 30 seconds after the last successful motor operation. Manual knob position is not tracked. Operations with uncertain results after a communication failure are not automatically replayed.

The relay requires the Pi/host. Standalone owner authentication on the XIAO, direct iPhone BLE control, and Apple Wallet home keys/NFC unlocking are not implemented.

## Files and downloads

| Location | Contents |
| --- | --- |
| [`onboarding/`](onboarding/README.en.md) | Card enrollment, encrypted vaults, existing-vault verification, minimal operation-key export |
| [`wired/`](wired/README.en.md) | C3 UART source, encrypted captures, legacy DPAPI import, bounded recovery and tests |
| [`relay/`](relay/README.en.md) | XIAO configuration, operation runtime, build, service and HomeKit setup |
| [`qsl1sec/`](qsl1sec/) and [`patches/`](patches/) | Fixed SEC002 delta, generation and initial installation tools |
| [`docs/`](docs/) | Installation, recovery, incident report, redistribution and testing scope |
| [`MANIFEST.json`](MANIFEST.json) | File list and hashes for the current source tree |

**Enrollment, relay, wired tools, and English guides are included in the [v0.9 release](https://github.com/bruiselea/qrio-sec002/releases/tag/v0.9) ZIP or latest source.** The existing [v0.1.0 release](https://github.com/bruiselea/qrio-sec002/releases/tag/v0.1.0) and old [`dist/` ZIP](dist/qrio-sec002-toolkit-v0.1.0.zip) are the original SEC002 kit and do not contain these additions.

Original project code is under the MIT License. Stock firmware, SDKs, APKs, device backups, owner keys, real Wi-Fi configuration, and generated XIAO firmware are not distributed. See [distribution scope and third-party rights](NOTICE.en.md) and [security scope](SECURITY.en.md).

## Sources and acknowledgments

We used **[bakueikozo's qriohack](https://github.com/bakueikozo/qriohack)** and the **[honeylab article](https://honeylab.hatenablog.jp/entry/2023/06/03/090731)** for prior hardware research, pin assignments, disassembly information, and independent firmware development. [Sources and acknowledgments](SOURCES.en.md) maps manufacturer documentation, fixed SDK references, archived APK analysis, ESPHome, Home Assistant, and other dependencies to their roles in this project.
