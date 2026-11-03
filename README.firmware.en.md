# SEC002 firmware protection kit (included in v0.9)

[日本語](README.ja.md) | English

This page describes the firmware delta kit. See the [project overview](README.en.md), [LAN relay](relay/README.en.md), [wired backup and bounded recovery](wired/README.en.md), and [boot failure report](docs/BOOT_FAILURE.en.md) for the other parts. The original v0.1.0 ZIP does not include the wired kit or English documentation.

**Stock firmware is not bundled. The wireless installer for an unmodified Q-SL1 is experimental.**

The kit provides code and instructions to install SEC002 on your original Qrio Q-SL1 using Bluetooth from Linux/Pi, without wiring the lock for this initial installation. Windows can control the Linux host over SSH. The lock itself does not connect to Wi-Fi.

## Read first

- The target must be an unmodified 1.4.01 unit that boots and advertises normally with working batteries. This wireless tool cannot recover a unit that does not advertise.
- Supported boot selection is SS1 at offset `0`, DS1 at `0x580`. The 26,845-byte stock DS1 must hash to `4679b688063dac92d7c326f3e98ba429291bf1140afc2f4b96a1694cb8741c81`. Other versions, layouts, or hashes cannot be forced.
- SEC002 disables known unauthenticated FWU CIDs and legacy OTA. **Subsequent firmware maintenance and rescue require wired UART**, including for an authenticated owner.
- There is no automatic boot rollback. Read [recovery preparation](docs/RECOVERY.en.md) before activation.
- The firmware installer retains existing owner data; it does not create owner keys or configure HomeKit. Those have [separate instructions](onboarding/README.en.md).

## What was verified

| Item | Evidence |
| --- | --- |
| Fixed delta applied to stock DS | Compared with the SEC002 image that ran on the owned unit; output hash `ccf6a88b…ec2e82` |
| SEC002 wired deployment | Performed on one owned unit with complete readback comparison |
| SEC002 operation | Two battery boots, owner authentication, no response to known FWU read requests, legacy OTA rejection, and normal lock/unlock completion responses; direct-test motor rotation was not visually observed |
| Wireless transfer and SS switching | Stock → DEV001 → stock demonstrated on the same unit |
| Public stock → SEC002 wireless workflow | **Not tested from start to finish on hardware**; experimental port combining those separate results |
| Other units or firmware versions | Not verified; mismatches are refused |

## Initial wireless installation

The [wireless guide](docs/WIRELESS_INSTALL.en.md) covers Linux preparation, discovery, encrypted backup, staging, activation, and verification. Commands select one explicit Bluetooth address and subsequently bind to the device identity stored in the encrypted backup. Read the complete procedure before using it.

You may transfer the release ZIP from Windows to Linux with `scp`. This initial wireless procedure has no Q-SL1 UART wiring step. Do not rerun the wireless installer on a unit already running SEC002.

## Original kit contents

- `qsl1sec/`: Linux BLE transport, fixed delta application, portable encrypted backups.
- `patches/sec002.json`: Original replacement bytes and source/output fingerprints, without the stock code image.
- `patches/sec002-assembly.txt`: Assembly representation of the project patch.
- `tests/`: Synthetic offline tests without Bluetooth.
- `docs/`: Installation, recovery, qualification and redistribution instructions.
- `LICENSE` and [NOTICE](NOTICE.en.md): MIT scope and third-party rights.

Backups use scrypt and AES-256-GCM rather than Windows-account-bound DPAPI. Enter passphrases locally with hidden input; they are not command arguments or log fields. Encrypted files can be moved to another PC, but you must retain the passphrase.

## Redistribution

Keep the original ZIP, its `SHA256SUMS.txt`, and the [redistribution notes](docs/REDISTRIBUTION.en.md) together. Never add generated firmware, `.private`, device reports or keys. Preserve the distinction between hardware evidence and the unqualified end-to-end wireless workflow.
