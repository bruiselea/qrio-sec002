# Relay testing scope

[日本語](TESTING.ja.md) | English

Checked on 2026-11-03 with one owned Q-SL1 and Seeed Studio XIAO ESP32C3.

| Item | Result |
| --- | --- |
| XIAO firmware | ESPHome 2026.10.2 / ESP-IDF 5.5.6 build and USB upload succeeded |
| Encrypted LAN | Noise API authentication and relay MAC verification succeeded from PC/Pi |
| BLE discovery | XIAO near the door received the registered unit |
| Owner operations | Normal authentication and ReadStatus succeeded through LAN→XIAO→BLE |
| HomeKit locking | With Pi farther away, the user confirmed locking; matched normal motor completion/LOCKED records |
| Public dependency separation | Extracted framing/authentication; compared with the original implementation using synthetic data and checked signatures, encryption and framing |
| Other units / long-term operation | Unverified |
| Complete fresh installation from the public guide | Not performed; relay setup assumes registered owner credentials and existing HA/MQTT |

## Offline tests

Run from the repository root using runtime dependencies; no network, BLE, stock firmware or real owner keys:

```sh
python relay/verify.py
```

The 13 tests cover raw advertisement bounds/identity, subscription lifetime, bond-update ordering, GATT scope and notifications, no write replay after failure, cancellation cleanup, API key/destination requirements, synthetic RSA authentication contracts, framing, worker exclusion and state expiry.

## Implementation details

With ESPHome 2026.10.2, raw advertisement subscription is retained throughout the GATT session because the subscribing API connection also receives GATT replies. Unpairing occurs before BLE connection, avoiding a bond-removal disconnect on the active link.

Uncertain motor results after LAN failure are not automatically replayed. There is no operation replay queue on either Pi or XIAO. Owner private keys are used inside the host process and not uploaded to the relay.

Wi-Fi and BLE share the XIAO antenna. Radio conditions, congestion and nearby metal affect results; no fixed range or latency is guaranteed. These relay results do not qualify the separate SEC002 wireless installer end to end.
