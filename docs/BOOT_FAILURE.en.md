# SEC001 boot failure: observations, possible causes and wired recovery

[日本語](BOOT_FAILURE.ja.md) | English

This report concerns one owned original Q-SL1. It stopped beeping/advertising after a wireless boot-selection change on 2026-11-01. UART inspection and recovery followed on 2026-11-03. This public report excludes full EEPROM, keys, card details, device addresses, PC paths, full-device hashes and unprocessed logs.

**The faulting instruction and exception PC have not been identified. Evidence strengthens the inference that SEC001's startup/RAM-layout changes caused the failure. The architectural reason wireless recovery was unavailable, and gaps in predeployment verification, are established.**

## Observed sequence

| Stage | Evidence retained in the records |
| --- | --- |
| Stage while running stock 1.4.01 | Transferred all 26,972 SEC001 bytes to inactive DS2 and compared readback. Stock DS1/selection retained; subsequent stock boot and owner authentication succeeded |
| Activate SEC001 | Rechecked candidate and SS2, disabled SS1 marker, then failed to discover/reconnect to BLE |
| Battery restarts and another host | No boot beep; neither Pi nor Windows detected advertisements |
| ROM UART on November 3 | Standard HCI responded; two independent 64 KiB EEPROM captures matched byte for byte |
| Fault-state comparison | Stock DS1 matched the normal backup; SS1's other 39 bytes matched. DS2 matched the saved deployed SEC001 candidate; SS2 matched the planned reference |
| First marker restoration attempt | An ACK arrived, but the marker stayed 00 and the entire EEPROM was unchanged; not treated as successful recovery |
| Subsequent wired writes with WP configured | Registering the existing ROM WP callback temporarily enabled verified page writes/full readback, retaining stock DS1 and owner storage |
| Demonstrated boot recovery | Staged and selected the previously boot-tested minimal DEV001 image in DS2. After disconnecting UART, battery boot restored beep/LED/advertising/version. Existing-key ReadStatus succeeded |
| Later SEC002 | Reworked protection without changing startup layout; UART deployment, boot, known-path rejection and owner authentication checked on the unit. HomeKit locking over XIAO was subsequently confirmed |

No mismatch between the deployed candidate and fault-state EEPROM was found. Matching transferred bytes do not prove the candidate can boot.

The first ACK-only operation and later effective WP-configured recovery are separate events. **There is no hardware record of standalone one-byte restoration followed by a normal stock boot.** The public [wired kit](../wired/README.en.md) states this qualification boundary.

## What SEC001 changed

To tie maintenance access to owner authentication, SEC001 hooked profile initialization and modified the L2CAP handler table. It appended 120 bytes of code near the RAM tail, added a DS record, and changed the dynamic-allocation boundary constant.

```text
ROM selects boot settings -> loads DS2 into RAM
  -> C startup, BSS initialization, allocation boundary setup
  -> BLE stack/profile initialization
  -> SEC001's added table operation
  -> GPIO and other initialization -> advertising
```

The added code lies before advertising. Failure there can prevent even the connection required for owner authentication. Its actual reachability/fault address was not recorded on the failing device. The [manufacturer's startup description](https://community.infineon.com/t5/Smart-Bluetooth/How-image-is-validated-during-bootup/td-p/198938) distinguishes application creation/initialization from subsequent event handling.

### A 32-byte memory-boundary discrepancy

Offline execution of captured startup code and comparison with the referenced SDK showed a discrepancy: the SDK adds 32 to the resident region's end and aligns to 16 bytes, while SEC001 directly used the added code's end. Specific references are [`spar_setup.c`, GCC allocation-boundary calculation](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/spar/common/spar_setup.c#L132) and [`spar_ram.ld`](https://github.com/j123m456/WICED-Smart-SDK/blob/79d9f0fcdbea76140cb8f69e25067bd09ddf0e40/Wiced-Smart/spar/gcc/spar_ram.ld#L100), at a fixed commit in a third-party SDK mirror. See [source provenance](../SOURCES.en.md).

| Item | Stock | SEC001 |
| --- | --- | --- |
| End of resident region / added code | `0x20A11C` | `0x20A200` |
| Allocation boundary actually set | `0x20A130` | `0x20A200` |
| Boundary under the same layout formula | `0x20A130` | `0x20A220` |
| Discrepancy | 0 | 32 bytes |

The discrepancy was verified. There is no trace of the allocator overwriting added code or a captured fault register. **It has not been proven that this caused the failure, and correcting those 32 bytes alone is not a demonstrated fix.** The manufacturer describes reuse of initialization RAM; apparently unused trailing space alone does not prove safe resident-code placement. See the [memory architecture documentation](https://community.infineon.com/t5/Knowledge-Base-Articles/BCM20732-Memory-Map-Architecture/ta-p/246756).

### Insufficient handler-table validation

The original hook checked only that the table pointer was nonzero. It did not sufficiently validate range, alignment, count bounds or presence of the required handler.

Offline checks showed that an initialized valid table worked; a nonzero invalid pointer could fault; and registration occurring after an empty-table pass could escape the guard. These are **conditional counterexamples**, not a reproduction of the actual device failure. The startup pointer was never captured on hardware, so the report does not conclude that an uninitialized table was the cause.

## Why preserved stock firmware could not be selected wirelessly

Stock DS1 remained in EEPROM, but activation changed SS1's leading marker from 01 to 00 so the ROM selected SS2 and the candidate. No boot monitor or automatic SS1 rollback was implemented.

The intended wireless recovery interface depended on BLE and owner authentication in the new application. A failure before advertising makes that interface unreachable. Moving the rollback call into another exception handler or resending commands cannot reach a receiver that is not running.

**Keeping an old image also requires a recovery path independent of the failed application.** ROM UART provided that path here. The absence of automatic rollback was a design/deployment decision on the implementation side.

## What predeployment checks missed

- Emulation replaced `bleprofile_Init` with an immediate return and did not execute its actual memory operations.
- Tests supplied an already initialized synthetic handler table rather than reproducing real ROM allocation and registration order.
- B9 record semantics/layout, interrupts, peripherals and sleep/wake behavior were not fully represented.
- Boundary tests compared the candidate with its own chosen constants, missing the independent SDK layout discrepancy.
- DEV001 changed only a display string. Its transfer and boot success did not establish safety for SEC001's startup and RAM-layout changes.
- Readback equality, selector transaction integrity, normal boot and recovery after failed boot were not sufficiently treated as separate properties.

Expected bytes and isolated function behavior are not proof of hardware boot. There is no evidence that the user's battery handling or card entry caused this boot failure.

## Changes in SEC002 and the public recovery kit

SEC002 reuses an existing OTA code region, adds no RAM region or DS records, and retains C startup, BSS end and dynamic-allocation boundaries. It validates handler-table range, alignment and count, and permits advertising only after protection is verified. See [security scope](../SECURITY.en.md).

This is not automatic recovery. SEC002 closes wireless FWU and legacy OTA; subsequent firmware maintenance/recovery requires UART. No claim is made that startup hooks or other firmware modifications cannot brick a device.

The public recovery kit compares a known-good original, a fault snapshot and fresh live captures, then limits the operation to restoring the marker when stock DS1/SS1 match. ACK, full readback, RAM cleanup and battery-only boot are separate checks. It has not been rerun against the working door lock as an end-to-end public-CLI hardware test.

## Public evidence and remaining limits

The [curated observations](evidence/SEC001.json) contain numerical/Boolean findings, hypotheses and unknowns extracted from privately retained records. Original logs and captures remain private, so public readers cannot independently reproduce the hardware capture comparison from this summary. It is an evidence summary rather than a full-dump release.

Synthetic wired tests cover mismatches, lost replies, ineffective writes, collateral changes, storage failures and cleanup failures. They do not reproduce hardware boot. The SEC001 faulting instruction, causality of the 32-byte discrepancy, other-unit behavior and an end-to-end public recovery hardware test remain unresolved or unperformed. The failed SEC001 deployment tools and stock code are not distributed.
