# Security scope

[日本語](SECURITY.md) | English

## Owner enrollment and relay

`onboarding/` saves an encrypted vault before enrollment, verifies the mutual card challenge before sending saved public keys, and distinguishes enrollment acknowledgment from authenticated operation over a new connection. Operation-key export requires a successful authenticated ReadStatus. It does not bypass authentication without the card, guarantee revocation of earlier owners or shared keys, or fully audit a second-hand unit's existing registrations.

Vaults use scrypt (N=32768, r=8, p=1) and AES-256-GCM. Recovery requires the owner's passphrase. Secrets are not accepted as command arguments. Exported `owner.json` contains plaintext operation credentials: POSIX creation uses mode 0600, while Windows inherits the destination directory ACL. Use private storage and do not publish even encrypted backups.

LAN transport uses the encrypted ESPHome API and verifies the relay's identity. Owner authentication runs on the host; RSA private keys are not stored on the XIAO. Holders of the API key can access the standard ESPHome Bluetooth proxy, so Wi-Fi details, API keys, and generated XIAO firmware must also remain private. Manual knob tracking, long-term operation, other units, and end-to-end fresh enrollment with the public CLI are not verified.

## SEC002 firmware

SEC002 is a limited mitigation that closes known maintenance L2CAP interfaces and legacy OTA on the supported 1.4.01 image. It is not a comprehensive audit or guarantee covering BLE/GATT, cryptography, physical access or mechanical security.

After profile initialization it disables active CID 0x00FA/0x002A table entries. An alternative long/audio handler prevents a successful result. It validates count, alignment and RAM bounds, and permits advertising only after successful application. Legacy OTA operation 9 is redirected to the existing NotAuthorized/session-clear path.

The patch reuses an existing OTA code region and retains the RAM layout and startup memory boundaries. A failed startup check can stop advertising; this is not automatic recovery. Subsequent firmware maintenance requires UART.

The wireless installer accepts only the fixed candidate fingerprint and implements no erase/Launch commands. Its write policy is limited to inactive DS2, SS2, the first byte of the unit's SS1, and temporary RAM WP settings. It reads 64 KiB twice initially and saves encrypted snapshots at each stage. Addresses and advertisement identities reduce target mistakes but do not cryptographically prove ownership. Select one nearby unit that you control.

## Wired recovery

`wired/` requires intact stock DS1 and the same other 39 SS1 bytes as the original known-good backup. Two fresh live captures must match each other and the supplied fault snapshot. The only persistent write restores the first marker byte to 01; ROM and WP state are checked before temporary changes. An ACK alone is insufficient: the other 65,535 bytes and restored RAM settings must be verified. Battery-only boot is checked separately after disconnecting UART. The public CLI has not been tested end to end on hardware.

UART is a physical maintenance interface, not software proof of ownership. Keep backups, passphrases, and output directories private. Loopback sends arbitrary data and must only be run with the lock disconnected. Selecting stock firmware also means SEC002 protection is not active for that boot.

## Reporting

Do not attach cards, keys, passphrases, backups or full dumps to public issues. Report versions, the stage where execution stopped, non-secret diagnostics, and synthetic reproductions. No dedicated reporting contact is configured in this package.

Background: [manufacturer FWU API documentation](https://infineon.github.io/btsdk-docs/BT-SDK/20736-A1_Bluetooth/API/group__utility.html). Implementation constraints are based on the inspected target ROM and owned-unit evidence, rather than the generic API description alone.
