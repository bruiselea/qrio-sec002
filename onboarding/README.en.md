# Enroll an owner and prepare operation credentials

[日本語](README.ja.md) | English

Use your Q-SL1 and its owner card to register new operation credentials locally. All generated keys are saved in an encrypted recovery vault before enrollment. **Export is allowed only after authenticated ReadStatus succeeds over a separate connection.** No lock/unlock, firmware update, memory-write or owner-deletion command is provided here.

The registration, authentication and MQ routines reimplement behavior analyzed from the old Android app 1.8.7 and the owned unit. See [sources](../SOURCES.en.md).

**Fresh enrollment with this public workflow has not been tested end to end on hardware.** The protocol was used on the owned unit, while the new persistence, resumption and export workflow was tested with a simulated peer. Do not re-enroll a working installation just to try the tools. Use the existing-vault path below if you already have a vault. See [testing scope](TESTING.en.md).

## Requirements

| Item | Condition |
| --- | --- |
| Lock and owner card | Your Q-SL1, working batteries, and the matching card's serial and security code |
| Physical confirmation | Remove the lock from the door for fresh enrollment and keep the knob accessible |
| Local archived APK | The supported library from your archived Android app 1.8.7, matching the fingerprint below |
| Host | Python 3.11+ on Windows, or Linux/Pi with BlueZ and D-Bus access |
| Bluetooth path | Host BLE or a provisioned XIAO relay and its private `relay.private.json` |
| Private storage | A local directory outside the repository, readable only by you; avoid shared/synchronized folders |

**The owner card alone is insufficient for this distribution.** New MQ public keys require coefficients read from the old APK. The APK, native library and coefficient table are not bundled or automatically downloaded. If you have no supported APK, new enrollment stops here. Existing-vault verification, operation-key export and daily operation do not need the APK.

Supported `lib/x86_64/libmq.so` SHA-256:

```text
725f3cbb447eed0a523d0844f371e657a3cc0c21059274dce520997dc3ad67ff
```

The APK is neither installed nor executed. The tool reads one bounded ZIP member, checks its fingerprint, and accesses ELF `MQ_COEF` in memory. There is no override for unsupported libraries.

## 1. Obtain source and create an environment

Run from the repository root. The old v0.1.0 release ZIP does not contain `onboarding/` or `relay/`.

```sh
git clone https://github.com/bruiselea/qrio-sec002.git
cd qrio-sec002
```

Windows PowerShell:

```powershell
python -m venv .venv-onboarding
.venv-onboarding\Scripts\python -m pip install -r requirements-onboarding.txt
$qrioPrivate = "$env:USERPROFILE\.qrio-sl1\onboarding"
New-Item -ItemType Directory -Force $qrioPrivate | Out-Null
```

Windows files inherit directory ACLs. Do not use a location readable by other users. The vault is encrypted; exported `owner.json` contains plaintext operation keys.

Linux/Pi:

```sh
umask 077
python3 -m venv .venv-onboarding
.venv-onboarding/bin/python -m pip install -r requirements-onboarding.txt
mkdir -p ~/.config/qrio-relay
chmod 700 ~/.config/qrio-relay
```

The following commands use Windows paths. On Linux, substitute `.venv-onboarding/bin/python` and paths such as `~/.config/qrio-relay/owner.qsl1`. Linux BLE operations require BlueZ and appropriate D-Bus access. Stop other software connecting to the same lock, including the normal HomeKit gateway or app, during these operations.

## 2. Check the APK

Replace `C:\path\to\your-archived.apk` with your local file.

```powershell
.venv-onboarding\Scripts\python -m onboarding inspect-apk --apk "C:\path\to\your-archived.apk"
```

A supported fingerprint indicates that the file can be read. For a format/fingerprint error, check the path, version and library availability. Do not proceed with an unsupported version.

## 3. Fresh enrollment

Place the **off-door lock** near the BLE host or XIAO. If it beeps during registration, turn the knob more than 90 degrees and return it. Do not remove batteries during the transaction. `--device-off-door` records that this physical preparation has been completed.

```powershell
.venv-onboarding\Scripts\python -m onboarding enroll --apk "C:\path\to\your-archived.apk" --vault "$qrioPrivate\owner.qsl1" --device-off-door
```

Enter the card serial, security code, and a **new recovery passphrase that you choose now**, using hidden terminal input. The new passphrase must have at least 12 characters and match on confirmation. Unicode, full-width characters and leading/trailing spaces are used exactly as entered. This is not the previous owner's password. Do not put secrets in chat or command arguments.

The workflow:

1. Scan for the card serial; refuse zero or multiple matching identities.
2. Generate two RSA keys, MQ keys and shared secrets. Create and read back the encrypted vault.
3. Verify the mutual card challenge before sending the **saved public keys**.
4. Complete physical confirmation and the registration follow-up; mark the vault `acknowledged`.
5. Close the connection, reconnect, and run ReadStatus with the saved credentials. Only success marks the vault `verified`.

BLE Just Works pairing establishes a link. It does not by itself prove owner enrollment; card verification and operation authentication are separate steps.

### Use an XIAO instead of host Bluetooth

Complete relay setup steps 1–3 and creation of `relay.private.json` in the [relay guide](../relay/README.en.md) first. Those steps do not require owner keys. Add the private relay configuration to enrollment:

```powershell
.venv-onboarding\Scripts\python -m onboarding enroll --apk "C:\path\to\your-archived.apk" --vault "$qrioPrivate\owner.qsl1" --device-off-door --relay-config "$qrioPrivate\relay.private.json"
```

Registration challenges and public keys pass through the relay as BLE messages. The RSA private key, MQ private key, card code and vault passphrase themselves are not uploaded to the XIAO. Keep its configuration private. Fresh enrollment through the XIAO also lacks an end-to-end hardware test in this public release.

## 4. Export owner.json

```powershell
.venv-onboarding\Scripts\python -m onboarding export --vault "$qrioPrivate\owner.qsl1" --output "$qrioPrivate\owner.json"
```

Export performs no device communication. It writes only eight operation fields from a verified vault into a new file. It excludes the card serial, MQ private key, storage RSA private key and passphrase. Existing outputs are never overwritten.

**`owner.json` is a plaintext credential capable of locking/unlocking.** Do not display, commit or share it. Transfer it over your own SSH/SFTP connection into the Pi's private `~/.config/qrio-relay/owner.json`, with mode 600 on Linux. Check [relay status](../relay/README.en.md), then follow [systemd credentials and HomeKit](../relay/SYSTEMD_HOMEKIT.en.md). Retain the encrypted recovery vault separately.

## Start from an existing vault

If you already have `owner-credential.qsl1`, keep an independent copy before proceeding. No APK, card or fresh enrollment is required for this path.

```powershell
.venv-onboarding\Scripts\python -m onboarding inspect --vault "$qrioPrivate\owner.qsl1"
.venv-onboarding\Scripts\python -m onboarding verify --vault "$qrioPrivate\owner.qsl1"
.venv-onboarding\Scripts\python -m onboarding export --vault "$qrioPrivate\owner.qsl1" --output "$qrioPrivate\owner.json"
```

Enter the recovery passphrase you originally chose. `verify` performs authenticated ReadStatus only and does not actuate the motor. Add `--relay-config` to `verify` when using the XIAO. Older `registered` state may indicate only an enrollment ACK, so it cannot be exported until it becomes `verified`.

## Interrupted enrollment and errors

| Situation | Next step |
| --- | --- |
| Passphrase or format error | Check with `inspect`; match case, Unicode and whitespace exactly; retain the vault |
| Lock not discovered | Check batteries, distance, other connections and host/relay configuration |
| Enrollment timeout or lost reply | **Try `verify` first**; enrollment may have completed despite the lost reply |
| Verification fails and partial enrollment needs resuming | Add **`--resume`** to the enrollment command with the same vault, matching card/APK, and physical preparation |
| `acknowledged` state | Registration replied, but operation authentication is unverified; export is refused |
| Rejection such as status 130/132 | Do not treat rejection as success; preserve the vault and investigate the link and registration/confirmation state |
| Existing output | Choose a new path rather than overwriting a known credential or vault |

There is no automatic enrollment retry or key regeneration. `--resume` reuses saved keys. Direct re-enrollment of `verified` or older `registered` vaults is refused; first use `verify`. A new failed verification removes any old verification marker and leaves `acknowledged`, blocking export. Re-enrollment from that state requires explicit `--resume`.

Before updates, the prior ciphertext is preserved as `owner.qsl1.backup-...`. The vault is atomically replaced from a temporary file in the same directory. The small `.lock` file prevents simultaneous use of the same vault; it can remain after exit, but the OS releases its lock. Keep all these files private. Forgotten passphrases cannot be bypassed by this tool.
