# Wired backup and stock boot-selector recovery

[日本語](README.ja.md) | English

Connect to your Q-SL1 over UART, save encrypted EEPROM captures, and **restore one boot-marker byte only when stock DS1 and the original SS1 remain intact**. A Windows PC can run the tools directly; a Raspberry Pi is optional.

The kit does not erase or rewrite the full EEPROM, DS1 or DS2, and cannot reconstruct corrupted stock firmware. Read the [boot failure report](../docs/BOOT_FAILURE.en.md) and [testing scope](TESTING.en.md).

**The new public recovery CLI has not been tested end to end on hardware.** It packages the C3 bridge, ROM communication, captures, WP configuration and selector operations used on one owned unit. It has not been rerun on the working door installation. The first historical marker-write ACK produced no EEPROM change; later demonstrated recovery included DEV001 staging and selection. This is not evidence of a standalone one-byte operation followed by a stock boot.

## Requirements

| Item | Condition |
| --- | --- |
| Your Q-SL1 | **Remove it from the door and remove all batteries before wiring** |
| Working CR123A batteries | Power the lock from its batteries |
| 3.3 V logic USB UART | Tested hardware was a C3 SuperMini running the included sketch; ordinary adapters can be selected with `--adapter uart-3v3` but are not hardware-tested here |
| Connection to the 12-pin, 0.5 mm FPC | A suitable breakout or careful fine-wire connection, with contact orientation and numbering confirmed |
| Three wires and a meter | TX, RX and common ground; check adjacent-pin shorts and logic voltage |
| Python 3.11+ host | Windows/Linux; building the C3 bridge additionally needs Arduino CLI and ESP32 Core 3.3.7 |
| **Same-unit known-good stock backup** | Required for recovery writes: full 64 KiB `.qsb` with stock 1.4.01 DS1 and SS1 from a confirmed normal boot |

Capture works without a known-good backup. Capturing data does not prove it will boot. Only the known stock DS1 layout and ROM are supported. Do not transplant another unit's EEPROM.

## 1. Host environment

Obtain the latest source and run from the repository root. The v0.1.0 release ZIP does not contain this kit.

```powershell
python -m venv .venv-wired
.venv-wired\Scripts\python -m pip install -r requirements-wired.txt
.venv-wired\Scripts\python -m wired --help
$qrioWired = "$env:USERPROFILE\.qrio-sl1\wired"
New-Item -ItemType Directory -Force $qrioWired | Out-Null
```

On Linux, use `.venv-wired/bin/python` and a private directory such as `~/.qrio-sl1/wired`, with `umask 077` and parent mode 700. On Windows, use an NTFS directory whose ACL allows only appropriate private access. Captures use the same [portable encrypted format](../qsl1sec/private.py) as the wireless kit and do not depend on a Windows account. Enter a passphrase of at least 12 characters using hidden local input.

## 2. Prepare the C3 UART bridge

Skip this section if using an ordinary 3.3 V USB UART. Disconnect the C3 from **the Q-SL1 and every other circuit** before USB connection. Back up any C3 program you need using your own procedure before replacing it; this kit does not automatically preserve or restore the prior C3 firmware.

Install [Arduino CLI](https://arduino.github.io/arduino-cli/latest/installation/) and the pinned ESP32 Core:

```powershell
arduino-cli core update-index --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
arduino-cli core install esp32:esp32@3.3.7 --additional-urls https://espressif.github.io/arduino-esp32/package_esp32_index.json
.venv-wired\Scripts\python wired\build_bridge.py --output-dir "$qrioWired\c3-build"
```

Use `--cli` for a specific CLI executable or `--config` for your private Arduino configuration. The output directory must be new. Building opens no serial port and flashes no device. Outputs are under `c3-build/firmware/`. Compilers and prebuilt C3 firmware are not bundled.

```powershell
.venv-wired\Scripts\python -m wired ports
arduino-cli upload --fqbn "esp32:esp32:esp32c3:CDCOnBoot=cdc,FlashSize=4M,FlashMode=dio,DebugLevel=none" --port COM_PORT --input-dir "$qrioWired\c3-build\firmware" wired\c3_uart_bridge
```

Replace `COM_PORT` with your C3's port. This uploads to the C3: ESP32-C3, 4 MB, DIO, native USB CDC enabled. This is a different program from the XIAO LAN relay. Using the same board replaces its previous relay program.

Unplug USB, wire **GPIO4 to GPIO5 only**, then reconnect USB. Keep the Q-SL1 disconnected.

```powershell
.venv-wired\Scripts\python -m wired loopback --port COM_PORT --qsl1-disconnected
```

The test verifies 65,536 bytes round trip, including arbitrary data. Never send this loopback test toward the lock. Unplug USB and remove the GPIO4–GPIO5 wire afterward.

## 3. Connect the lock with three wires

**Disconnect both the Q-SL1 batteries and C3 USB before wiring.** F numbers refer to the Q-SL1 flat cable, not C3 GPIO numbering. Confirm contact orientation and breakout labels physically and with continuity measurements.

| Q-SL1 | C3 SuperMini | Ordinary 3.3 V USB UART |
| --- | --- | --- |
| **F9: Programming RX** | **GPIO5: TX** | TX |
| **F10: Programming TX** | **GPIO4: RX** | RX |
| **F11: GND** | **GND** | GND |

**Do not connect F1/F2/F3, or the C3/adapter's 5 V, 3V3 or VCC pins to the lock.** Power the lock from its own batteries. Use 115200 baud, 8N1, no flow control; never 5 V UART or RS-232 levels.

Connect C3 USB first so TX is idle High, then insert the lock batteries. This entered ROM programming mode on the owned unit. Absence of the application's beep/advertising in that mode alone does not imply a boot failure. See the [manufacturer's reset-level and boot-mode explanation](https://community.infineon.com/t5/Smart-Bluetooth/How-image-is-validated-during-bootup/td-p/198938).

Pin assignments and photographs were researched using [bakueikozo/qriohack](https://github.com/bakueikozo/qriohack) and the [honeylab article](https://honeylab.hatenablog.jp/entry/2023/06/03/090731). Their photos/code and the SDK are not reproduced here. See [sources and scope](../SOURCES.en.md).

## 4. Probe ROM and capture the fault state

Close serial monitors and other applications using the port first.

```powershell
.venv-wired\Scripts\python -m wired probe --port COM_PORT --device-off-door
.venv-wired\Scripts\python -m wired backup --port COM_PORT --device-off-door --output-dir "$qrioWired\fault-01"
```

For an ordinary adapter, add `--adapter uart-3v3` to both commands. Software cannot verify logic voltage; confirm 3.3 V levels physically.

`probe` queries standard HCI version information. `backup` makes two independent full 64 KiB reads without RAM/EEPROM writes. It independently encrypts and verifies `fault-01/capture-pass1.qsb` and `capture-pass2.qsb`, and only completes when the reads match. Existing directories are not reused. Already saved encrypted captures remain after a mismatch.

## 5. Supply the original known-good backup

Use a complete `.qsb` captured by this kit while the same lock booted normally, or the wireless kit's [`original.qsb`](../docs/WIRELESS_INSTALL.en.md). It must be a same-unit confirmed stock-boot backup.

For an older Windows `.dpapi.json`, perform this offline conversion **on the original Windows account and PC**:

```powershell
.venv-wired\Scripts\python -m wired import-dpapi --input "C:\path\to\your-original.dpapi.json" --output "$qrioWired\original.qsb"
```

The old file is retained. The importer verifies full size and integrity, then encrypts with a new passphrase without writing plaintext firmware. There is no bypass if Windows cannot decrypt the original. Converting a fault-state capture does not make it a known-good backup.

```powershell
.venv-wired\Scripts\python -m wired inspect --backup "$qrioWired\original.qsb"
.venv-wired\Scripts\python -m wired inspect --backup "$qrioWired\fault-01\capture-pass1.qsb"
```

Inspection checks stock DS1, SS1 structure and the marker. It does not print full-EEPROM hashes, Bluetooth addresses or key bytes.

## 6. Plan offline, then execute only if needed

```powershell
.venv-wired\Scripts\python -m wired restore-stock --original "$qrioWired\original.qsb" --snapshot "$qrioWired\fault-01\capture-pass1.qsb"
```

The default is an **offline plan that never opens a port**. Both stock DS1 copies must match the fixed 26,845-byte hash. The other 39 SS1 bytes must match the original; the marker must be 00 or 01. There is no override for another version or corruption. Partial SS2/DS2 is left untouched; the operation selects preserved stock SS1.

For execution, keep the lock off the door and provide a new output directory:

```powershell
.venv-wired\Scripts\python -m wired restore-stock --original "$qrioWired\original.qsb" --snapshot "$qrioWired\fault-01\capture-pass1.qsb" --execute --port COM_PORT --device-off-door --output-dir "$qrioWired\restore-01"
```

Enter the original and current capture passwords, followed by a new password for this transaction's captures, all through hidden input.

1. Read the entire live EEPROM twice, save both encrypted copies, and verify equality with each other and the supplied fault snapshot.
2. Match two ROM fingerprints, HCI version, WP state and 16-byte page configuration before writing.
3. Temporarily configure only the WP pin and an existing ROM WP callback. Load no executable code/minidriver.
4. Request one write of 01 to EEPROM offset 0. An ACK alone is insufficient.
5. Read and encrypt all 64 KiB again; require the planned image and **all other 65,535 bytes unchanged**.
6. Restore and read back temporary RAM settings. Normal boot is checked separately.

If the marker is already 01, no persistent write is issued. `result.receipt.json` records stages and verification. Short writes and communication errors never cause EEPROM write replay. After a lost reply, the result may be unknown: make a fresh backup before deciding what to do next. Failure to verify WP cleanup also prevents completion.

## 7. Disconnect UART and check battery-only boot

Remove all lock batteries → unplug C3 USB → disconnect F9/F10/F11 → wait about 15 seconds → insert only the lock batteries. Do not judge application boot while UART still forces programming mode.

Check beep/LED, BLE advertisement/version, then authenticated ReadStatus with your credentials. The recovery CLI does not move the motor. `completed: true` means selector restoration and readback completed, not proof of normal boot or actuation. It never automatically sets `normal_boot_verified` to true.

Booting stock means SEC002 protection is inactive for that boot. Confirm firmware and operation before resuming HomeKit. This one-byte procedure cannot repair damaged stock DS1/SS1, missing backups, or a nonresponsive UART.

Never commit captures, encrypted backups, personal receipts or generated artifacts. The public kit contains original source, instructions and synthetic tests only.
