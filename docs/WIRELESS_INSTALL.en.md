# Initial wireless installation on an unmodified Q-SL1

[日本語](WIRELESS_INSTALL.ja.md) | English

Use only on your own Q-SL1. The transport requires Bluetooth on Linux/Pi. Windows standard BLE APIs/Web Bluetooth cannot send the required custom L2CAP CID; Windows can control Linux over SSH.

```text
Windows PC (optional) -- SSH/LAN -- Linux PC / Raspberry Pi -- Bluetooth -- Q-SL1
```

**The public stock-to-SEC002 wireless workflow has not been tested end to end on hardware.** Wireless transfer evidence and SEC002's separate wired deployment evidence are distinct. If advertising stops, recovery requires wired access; there is no automatic stock rollback.

## 1. Prepare the lock and host

Remove the lock from the door. Confirm normal boot/advertising with working batteries. Put Linux/Pi nearby and stop other software connecting to the same lock. Only if this project's HomeKit service is running, stop it:

```sh
sudo systemctl stop qrio-sl1-home.service
```

This installer uses no owner key because the known maintenance interface does not require owner authentication. Normal operation after installation still requires valid registered owner credentials; this tool does not enroll them.

Use Python 3.11+, BlueZ and a working Bluetooth adapter. Debian/Raspberry Pi OS preparation:

```sh
sudo apt update
sudo apt install python3-venv bluez unzip
```

Transfer and unpack the release ZIP. Windows PowerShell example; replace the SSH host:

```powershell
scp .\qrio-sec002-toolkit-v0.1.0.zip YOUR_USER@YOUR_PI:~/
scp .\SHA256SUMS.txt YOUR_USER@YOUR_PI:~/
ssh YOUR_USER@YOUR_PI
```

Continue in the Linux terminal:

```sh
sha256sum -c SHA256SUMS.txt
unzip qrio-sec002-toolkit-v0.1.0.zip
cd qrio-sec002-toolkit-v0.1.0
bash bootstrap-linux.sh
.venv/bin/python -m unittest discover -s tests -v
```

A matching ZIP hash verifies file equality, not the publisher's identity. Confirm the source as well. Bootstrap only installs dependencies in a venv; it does not connect to or write the lock. There is no `curl | sudo` step.

## 2. Select your lock's Bluetooth address

```sh
sudo .venv/bin/python -m qsl1sec scan --seconds 10
```

Replace the example `AA:BB:CC:DD:EE:FF` below with the discovered address of your controlled unit. If multiple units appear, identify one you can physically distinguish before proceeding. Later stages bind to the address and 128-bit advertisement identity saved in the encrypted backup.

## 3. Save two full EEPROM reads before writes

```sh
sudo .venv/bin/python -m qsl1sec backup \
  --address AA:BB:CC:DD:EE:FF --output .private/original.qsb
```

Choose a new backup passphrase of at least 12 characters and enter it twice locally. Never put it in chat, issues or command arguments. The tool reads 64 KiB twice, requires exact equality and supported DS1, then encrypts and verifies the saved backup. No device memory write occurs at this stage.

Keep an independent private copy of `original.qsb`. Full EEPROM contains owner information; never publish it even encrypted. This new backup password is one you choose, not the previous owner's password.

## 4. Build and stage SEC002 in the inactive region

```sh
sudo .venv/bin/python -m qsl1sec stage --backup .private/original.qsb
```

The fixed delta is applied locally and the SEC002 fingerprint checked. A fresh encrypted full snapshot is saved before transfer into DS2. Writes are at most 11 bytes and never cross a 16-byte page boundary. Pages and the full expected 64 KiB image are checked. Stock DS1, SS1 and owner storage are not written during staging.

The tool restores temporary WP configuration and waits 13 seconds before confirming stock 1.4.01 still boots. This stage does not select SEC002. Bluetooth conditions can make it take several minutes or longer; keep power stable while progress continues.

Optional local-only build:

```sh
.venv/bin/python -m qsl1sec build \
  --backup .private/original.qsb --output .private/SEC002.qsb
```

The generated output is encrypted but contains stock code. Do not add it to a distribution.

## 5. Activate

Run only after successful staging and preserving the backup:

```sh
sudo .venv/bin/python -m qsl1sec activate --backup .private/original.qsb
```

The tool rechecks stock DS1, your SS1 and the full SEC002 candidate. It clones SS1 to SS2 with the DS2 reference, verifies it, then changes the first SS1 byte. It restores WP configuration, closes the connection and waits for the FWU watchdog restart.

It reconnects for `Q-SL1 / SEC002`, checks that a known ROM-address-zero read preparation request receives no response, and verifies that GATT remains responsive. It does not perform erase, write or code-execution attack tests.

**Wireless firmware updating is closed from this point onward.** Repeating commands cannot necessarily recover a nonbooting unit. Follow [recovery guidance](RECOVERY.en.md).

## 6. Check after reboot

```sh
sudo .venv/bin/python -m qsl1sec verify --backup .private/original.qsb
```

Repeat this verification after a battery power cycle. It checks version, rejection/no response on the known read path, and GATT responsiveness; it is not an owner-authentication, physical motor or comprehensive security test. Separately verify your owner credentials/HomeKit while the unit remains off the door.

If you stopped your existing gateway, resume it after successful checks:

```sh
sudo systemctl start qrio-sl1-home.service
```

The tool does not upload backups or firmware to a cloud. Setup dependencies, SSH and the target Bluetooth link account for its network use.
