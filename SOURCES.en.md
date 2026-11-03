# Sources and acknowledgments

[日本語](SOURCES.md) | English

This project builds on prior hardware research, manufacturer documentation, analysis of the old application and an owned unit, and open-source communication infrastructure. This document maps references to their uses. Source inventory dated 2026-11-03.

## Q-SL1 prior research: bakueikozo / honeylab

- [bakueikozo/qriohack](https://github.com/bakueikozo/qriohack) provided the starting point for the programming FPC pinout, UART connection and independent application development with WICED. The retrieved reference revision was [`c0aab09b131fe390cc376aab45d4e0512efbd8ea`](https://github.com/bakueikozo/qriohack/tree/c0aab09b131fe390cc376aab45d4e0512efbd8ea).
- honeylab's [2023-06-03 article about reprogramming the first-generation Qrio Lock](https://honeylab.hatenablog.jp/entry/2023/06/03/090731) provided prior disassembly, circuit/I/O research, discovery of the hidden flat cable, and independent-firmware results.

We thank the author for publishing those findings. Upstream photographs, circuit diagrams, article text and OBAQ source are not reproduced here. This project's SEC002 delta, owner authentication, UART recovery and LAN relay are not presented as implementations or tests performed by that author.

## Broadcom/Cypress/Infineon ROM, startup and update references

| Reference | Use |
| --- | --- |
| [Infineon: BCM20732 Memory Map Architecture](https://community.infineon.com/t5/Knowledge-Base-Articles/BCM20732-Memory-Map-Architecture/ta-p/246756) | ROM/RAM/EEPROM organization and RAM reuse after initialization for the BCM20732/36/37 family |
| [Infineon: How image is validated during bootup?](https://community.infineon.com/t5/Smart-Bluetooth/How-image-is-validated-during-bootup/td-p/198938) | BLE/application creation order and UART RX sampling for programming mode |
| [Infineon: 20736-A1 FWU/utility API](https://infineon.github.io/btsdk-docs/BT-SDK/20736-A1_Bluetooth/API/group__utility.html) | API/function background, not proof of exact Q-SL1 ROM compatibility |

Research also used [j123m456/WICED-Smart-SDK](https://github.com/j123m456/WICED-Smart-SDK/tree/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40) at commit `79d9f0fcdbea76140cb8f69e25067bd09ddf0e40`. **This is a third-party SDK mirror, not the manufacturer's official distribution endpoint.**

- [`spar/common/spar_setup.c`, GCC startup](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/spar/common/spar_setup.c#L132): BSS initialization and allocation-boundary calculation, adding 32 to the resident end and aligning to 16 bytes. This is the specific comparison reference for the incident's 32-byte discrepancy.
- [`spar/gcc/spar_ram.ld`](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/spar/gcc/spar_ram.ld#L100): BSS/setup placement and subsequent dynamic memory use.
- [`bleapp/utils/bleappfwu.h`](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/bleapp/utils/bleappfwu.h) and [`bleapp/lestack/l2cap/lel2cap.h`](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/bleapp/lestack/l2cap/lel2cap.h): declaration/structure references for firmware updates and L2CAP.

SDK headers, libraries and native ROM code are not bundled. Generic documentation alone is not treated as evidence of the unit's fault state or actual hardware behavior.

## Owner enrollment and MQ: archived application and unit analysis

Enrollment/authentication messages in `onboarding/` and `relay/qrio_protocol.py` reimplement behavior analyzed from Android package `me.qrio.smartlock` version 1.8.7 and the owned Q-SL1's communication/captured data. The old APK was a behavioral reference; no clean-room claim is made.

The archived APK was obtained through a third-party archive. The historical acquisition path was the [APKPure package page](https://apkpure.net/qrio-smart-lock/me.qrio.smartlock), recorded here as provenance rather than an official Qrio download. Public tools only read a file supplied locally by the user; they do not download, install or run APKs.

MQ generation was referenced against `MQ_COEF` and native processing in that APK's `lib/x86_64/libmq.so`. The Python output matched memory-only emulation of the original processing for nine synthetic inputs. The APK, coefficient table and native library are not distributed.

The supported-library hash is a file fingerprint, not an owner's key. A fingerprint match alone guarantees neither official authenticity of a third-party distribution nor redistribution permission. See [enrollment prerequisites](onboarding/README.en.md) and [distribution scope](NOTICE.en.md).

## C3/XIAO and home integration

| Reference | Role |
| --- | --- |
| [Espressif: ESP32-C3 USB Serial/JTAG](https://docs.espressif.com/projects/esp-idf/en/stable/esp32c3/api-guides/usb-serial-jtag-console.html) | Native USB architecture/constraints; the bridge sketch was implemented by this project |
| [Arduino CLI](https://arduino.github.io/arduino-cli/latest/installation/) / [Arduino ESP32 Core](https://github.com/espressif/arduino-esp32) | C3 build and USB upload; tested with Core 3.3.7 |
| [Seeed: XIAO ESP32C3 Wi-Fi/antenna](https://wiki.seeedstudio.com/XIAO_ESP32C3_WiFi_Usage/) | Board, antenna and Wi-Fi reference |
| [ESPHome Bluetooth Proxy](https://esphome.io/components/bluetooth_proxy/) / [Native API](https://esphome.io/components/api/) | ESPHome supplies the XIAO's BLE proxy and encrypted LAN infrastructure |
| [aioesphomeapi](https://github.com/esphome/aioesphomeapi) | Host API client; raw-advertisement subscription lifetime and connection handling were checked against the used version and hardware |
| [Home Assistant HomeKit Bridge](https://www.home-assistant.io/integrations/homekit/) / [MQTT Lock](https://www.home-assistant.io/integrations/lock.mqtt/) | Home Assistant supplies the MQTT entity/HomeKit exposure, HomeKit implementation and pairing infrastructure |

ESPHome and HomeKit Bridge were not developed by this project. This repository supplies its own configuration, connection code and instructions for using them.

## Main libraries

- [Bleak](https://github.com/hbldh/bleak): host BLE.
- [dbus-fast](https://github.com/Bluetooth-Devices/dbus-fast): Linux D-Bus and pairing agent.
- [cryptography](https://github.com/pyca/cryptography): RSA, AES, scrypt and encrypted backups.
- [Eclipse Paho MQTT Python](https://github.com/eclipse-paho/paho.mqtt.python): gateway MQTT.
- [pyserial](https://github.com/pyserial/pyserial): host UART.
- [pyelftools](https://github.com/eliben/pyelftools): reading the user-supplied ELF as data.
- [Unicorn](https://github.com/unicorn-engine/unicorn) and [Capstone](https://github.com/capstone-engine/capstone): development-time emulation/disassembly using private reference data; not public-runtime dependencies.

Direct dependency pins are in `requirements*.txt`. Each dependency retains its own license; this project's MIT license does not replace those terms. Redistributing generated ESPHome/Arduino firmware requires separately checking the applicable conditions, beyond this source-only release.

## References versus hardware evidence

Generic documented behavior, APK/ROM analysis, synthetic tests and measurements on one owned unit are distinct. Qualification is recorded for [firmware](docs/TESTING.en.md), [enrollment](onboarding/TESTING.en.md), [wired recovery](wired/TESTING.en.md), and [relay](relay/TESTING.en.md). The [curated incident evidence](docs/evidence/SEC001.json) summarizes private records rather than reproducing their logs or dumps.
