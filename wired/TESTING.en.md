# Wired kit testing scope

[日本語](TESTING.ja.md) | English

## Underlying operations previously checked on hardware

On 2026-11-03, one owned Q-SL1 and C3 SuperMini used GPIO5→F9, GPIO4→F10 and GND→F11. Verified operations included a standalone 65,536-byte C3 loopback, 115200 8N1 ROM communication, two independent full EEPROM reads, existing-ROM WP configuration, write/readback and temporary-setting restoration.

The demonstrated recovery staged/selected DEV001 in DS2 and verified battery-only boot and existing owner authentication after disconnecting UART. The first marker request without WP setup returned an ACK but changed no EEPROM. A standalone marker-only recovery followed by stock boot, the new public CLI end to end, ordinary USB UART adapters and other units are unverified.

## Public synthetic tests

From the repository root, with `requirements-wired.txt` installed:

```sh
python -m unittest discover -s wired/tests -v
python -m unittest discover -s tests -v
```

Tests use no serial port, BLE, SSH, actual lock or stock firmware. On 2026-11-03, fresh dedicated environments passed 27 wired tests on Windows/Python 3.14 and 26 on Pi/Python 3.11, with one Windows-only DPAPI test skipped on Pi. The existing 11 firmware-tool tests passed in both environments.

Coverage includes:

- Fragmented HCI replies, rejection, short transmission, timeout, echoed commands and malformed frames; no request replay.
- Read bounds for EEPROM/fixed ROM/WP fields and writes limited to fixed WP values plus one stock marker byte.
- Portable encryption shared with wireless backups, wrong passphrases, overwrite refusal and POSIX mode 600.
- Legacy Windows DPAPI import using synthetic data; skipped on Linux.
- Matching SS1/fixed stock DS1/recognized markers, with wrong-unit-like SS1 changes, corruption and unknown markers rejected.
- All 1,678 possible 16-byte DS2 staging cut positions produce a marker-only recovery plan even with partial SS2.
- Two fresh independent encrypted captures matching the supplied snapshot; save failures or mismatches block RAM and EEPROM writes.
- ROM/WP mismatches, ACK without effect, lost replies, collateral changes, receipt-write failures and WP cleanup failures never become success.
- Offline plan by default; incomplete execution-preparation arguments never open the port.

Synthetic firmware and patched test fingerprints avoid distributing stock code. The production CLI has no fingerprint override. Simulation does not prove hardware EEPROM effects or boot.

## C3 build and private-data comparison

The public C3 sketch matches the original source used for hardware loopback. On 2026-11-03 it compiled from the public layout using Arduino ESP32 Core 3.3.7: 303,628 program bytes and 14,968 static RAM bytes. No device was flashed during this packaging task. Generated firmware is not bundled.

Memory-only inspection of retained normal/fault captures confirmed the public recovery policy plans exactly one marker-byte change. Independent capture equality, DS2's match to deployed SEC001, the planned SS2, ROM fingerprints, and later DEV001 boot/authentication records were rechecked. Firmware, owner storage and whole-EEPROM hashes remain private. These checks did not execute the public recovery command on hardware.
