# Redistribution

[日本語](REDISTRIBUTION.ja.md) | English

The combined [v0.9 release](https://github.com/bruiselea/qrio-sec002/releases/tag/v0.9) distributes the tagged source as `qrio-sec002-v0.9.zip` and `SHA256SUMS-v0.9.txt`, including enrollment, relay, wired recovery and English documentation. The v0.1.0 ZIP described below remains a historical release.

The original firmware delta release consists of `qrio-sec002-toolkit-v0.1.0.zip` and its `SHA256SUMS.txt`. Current enrollment/relay/wired tools and English documents are in the [repository source](https://github.com/bruiselea/qrio-sec002); the old ZIP has not been replaced. Original project code, patches and documentation use MIT. This does not license third-party stock code. Retain [NOTICE](../NOTICE.en.md).

## Included and excluded data

The kit contains original Python tools, 248 bytes of replacement data, source fingerprints, project assembly, synthetic tests, instructions and dependency pins. `MANIFEST.json` hashes the current source files.

Never add stock/generated SEC002 firmware, EEPROM/ROM dumps, SDKs, APKs, device backups (even encrypted), owner cards/keys, HomeKit settings or private logs. Generated SEC002 retains stock code. Dependencies are obtained separately; a distribution bundling them would require separately checking their licenses/notices.

The current source may include original `onboarding/` tools, `relay/` runtime/configuration and instructions, `wired/` sketch/recovery/tests, and the incident report with curated evidence. Exclude APK/native MQ data, `.qsl1` and backups, `owner.json`, real `relay.private.json`, `secrets.yaml`, generated XIAO/C3 artifacts, full-device hashes and personal receipts. Preserve prerequisites and the lack of public-workflow end-to-end hardware qualification.

## Example description of the original firmware ZIP

> A SEC002 delta and experimental initial wireless installer for an owned Q-SL1 with the known stock 1.4.01 DS1 layout. Stock firmware and device keys are not bundled. Linux/Pi Bluetooth reads the user's unit and applies a fixed patch. Separate wireless-transfer/selection and SEC002 wired-deployment results exist on one owned unit, but this public stock-to-SEC002 wireless sequence has not been tested end to end on hardware. Subsequent maintenance/recovery requires UART; no automatic boot rollback. The original ZIP contains no UART recovery program.

A prepared release is not evidence of qualification on someone else's unit. Do not advertise guaranteed no-brick installation, comprehensive vulnerability remediation or unlimited wireless firmware maintenance.

## Checks before publication

- Retain README, installation/recovery/testing scope, LICENSE, NOTICE and MANIFEST.
- Run `python -m unittest discover -s tests -v`; recompute the original ZIP checksum.
- Inspect the archive for private backups, `.private`, `.qsb`, `.dpapi.json`, firmware binaries, keys and hardware logs.
- Use actual published download URLs rather than nonexistent release links.

The old ZIP and latest source have different contents. For source redistribution, keep the root manifest consistent and preserve qualification limits, supported-APK prerequisites and language links.
