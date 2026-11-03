# Interrupted operations and wired recovery preparation

[日本語](RECOVERY.ja.md) | English

The original v0.1.0 ZIP contains the initial wireless installer and no wired recovery program. **Current source includes a [wired backup and bounded recovery kit](../wired/README.en.md)** with passphrase-encrypted captures and local conversion of legacy DPAPI backups. It restores the stock boot marker only when a same-unit known-good backup is available and stock DS1/SS1 remain intact. Its public CLI has not been tested end to end on hardware. C3 source is included, not compiled binaries.

The [SEC001 incident report](BOOT_FAILURE.en.md) distinguishes observations and hypotheses. The first marker ACK changed nothing; subsequent WP configuration and DEV001 staging/selection produced verified boot recovery.

## Where an interrupted operation leaves the lock

| Stage | Device changes | Next checks |
| --- | --- | --- |
| scan / backup / build | No EEPROM writes | Boot/advertising, selected address, competing clients and distance. Never force a different firmware/hash |
| Mid-stage | Part of DS2, temporary RAM WP settings | Stock SS1 remains selected. Wait at least 15 seconds after termination, check stock boot, then inspect records and new captures before replanning |
| Mid-activation SS2 creation | Part of SS2; stock SS1 before final commit | On a write exception, recovery may be attempted only while the same connection remains alive. Check `pre_boot_selector_recovery_verified` |
| SS1 commit or later | SS2 selects SEC002; SS1 marker disabled | Check advertising/version. If boot fails, use wired ROM access; repeating wireless commands is not a recovery strategy |
| Normal SEC002 boot | FWU and legacy OTA closed | Rejection of wireless memory/update requests is expected. Later firmware maintenance is wired |

`.private/*.receipt.json` records completed steps. Do not infer success without `completed` or `boot_verified`. Writes are not replayed after disconnect. Never overwrite the first `original.qsb` with an intermediate or fault-state capture.

Staging preserves stock selection, but does not guarantee EEPROM behavior during every power failure or hardware fault. A failed SEC002 startup check can suppress advertising and require UART.

## Verified wired interface

ROM UART programming mode responded even when the application did not boot. Provide a 3.3 V logic UART adapter, a connection to the 12-pin 0.5 mm FPC, three wires, working CR123A batteries, and your encrypted backup. A C3 SuperMini can act as an adapter with the included USB CDC–UART bridge.

F numbers refer to the **Q-SL1 flat cable**. Check contact face and orientation; breakout markings may not match the same physical view.

| Q-SL1 | C3 SuperMini | Direction |
| --- | --- | --- |
| F9, programming RX | GPIO5, bridge TX | C3 → Q-SL1 |
| F10, programming TX | GPIO4, bridge RX | Q-SL1 → C3 |
| F11 | GND | Common ground |

The bridge uses 115200 baud, 8N1 and no hardware flow control. An unprogrammed C3 is not a UART adapter.

Wire with lock batteries and C3 USB disconnected. On the owned unit, connecting C3 USB first to establish idle-High TX, then inserting lock batteries entered ROM mode. **Do not connect F1/F2/F3 or the C3 5V/3V3 pins.** Power the lock with batteries. For normal boot, remove batteries, unplug/disconnect the bridge and all three wires, then boot with batteries alone.

## Conditions for ROM recovery

1. Query HCI Read Local Version (0x1001) and bounded Read RAM (0xFC4D) before any loader/erase operation. Make and encrypt two independent full 64 KiB reads and require equality.
2. Match SS1 configuration to a known-good backup from the **same unit**, and verify the preserved stock DS1. Do not transplant another unit's EEPROM or owner storage.
3. Validate ROM and runtime WP settings. The inspected ROM used WP pin field `0x2008AB` and callback field `0x200DA8`. Preserve/restore original values and never write these addresses unconditionally on another ROM.
4. When stock DS1 and the other 39 SS1 bytes remain intact, the persistent change can be limited to EEPROM offset 0 becoming 01, using Write RAM (0xFC4C) through alias `0xFF000000`. An unknown ACK result must not trigger automatic replay.
5. Read all 64 KiB afterward, verify the one-byte plan and unchanged remaining data, restore temporary RAM settings, then separately check battery-only boot.

This describes the supported layout, not universal recovery. Restoring a marker cannot repair damaged DS1/SS1. The actual [current-source commands](../wired/README.en.md) are absent from the old ZIP. Do not activate with the assumption that every failure is recoverable without wired tools.

Prior FPC/pin research: [bakueikozo/qriohack](https://github.com/bakueikozo/qriohack). Upstream photographs/source are not reproduced. See [all sources](../SOURCES.en.md).
