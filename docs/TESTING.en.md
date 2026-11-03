# Firmware testing scope and reproduction

[日本語](TESTING.ja.md) | English

## Included synthetic tests

```sh
.venv/bin/python -m unittest discover -s tests -v
.venv/bin/python -m qsl1sec --help
```

These require no Bluetooth, owner keys or stock firmware. Eleven tests cover delta bounds/record structure/overlap rejection, write policy, authenticated encrypted storage and tamper refusal, ACL framing and stale connection-handle targeting, receiver cancellation cleanup, ROM/runtime mismatch refusal, inactive-region preservation, and interruptions/lost ACKs at every commit write. They do not reproduce physical EEPROM power-loss behavior, radio interference or motor movement.

## Private reference-data comparison

Applying the public fixed delta to the locally retained stock DS produced the exact SEC002 image used on hardware.

| Data | SHA-256 |
| --- | --- |
| Stock DS1, 26,845 bytes | `4679b688063dac92d7c326f3e98ba429291bf1140afc2f4b96a1694cb8741c81` |
| SEC002 DS, 26,845 bytes | `ccf6a88bfb1d9b4dd7568bc8abbb386522518435efa564041ecfd29baeec2e82` |

No unit-specific full-EEPROM hash is a support prerequisite. SS1 is cloned from each unit with only boot selection changed. DS record types/order/lengths, RAM mapping and CRT/BSS/heap boundaries are preserved; no new DS records/RAM regions are added.

Reference firmware, EEPROM and owner data remain private and are not test fixtures. The public ZIP alone cannot reproduce all hardware evidence.

## Hardware evidence

By 2026-11-03, the same owned unit demonstrated:

- Stock → DEV001 → stock using Linux raw HCI/custom L2CAP staging and SS selection.
- SEC002 staging/full readback/selection using ROM UART.
- Two SEC002 battery boots, version, no response to known FWU read requests and subsequent responsive GATT.
- Owner authentication, ReadStatus, authenticated legacy OTA operation 9 rejection, and normal lock/unlock completion responses; direct-test motor rotation was not visually observed.
- Resumed HomeKit integration and reduced connection latency while retaining per-operation BLE connections. Precise end-to-end Home app latency still needs measurement.

**The public stock-to-SEC002 wireless workflow has not been tested from start to finish on hardware.** The working unit was not downgraded to repeat it. Qualification uses fixed-image comparison, synthetic failure tests and Linux offline tests. Other units/versions, all power-failure conditions and overall BLE implementation security are unverified.
