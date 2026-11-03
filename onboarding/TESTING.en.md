# Enrollment and vault testing scope

[日本語](TESTING.ja.md) | English

The public enrollment workflow has not been rerun against the working, door-mounted unit. It reuses the protocol previously used on that unit and adds public persistence/resumption/export code. **Fresh enrollment using the public command sequence, including through the XIAO, has not been tested end to end on hardware.**

## Reproducible synthetic tests

Run from the repository root with `requirements-onboarding.txt` installed:

```sh
python -m unittest discover -s onboarding/tests -v
python relay/verify.py
python -m unittest discover -s tests -v
```

No APK, hardware, network connection or actual owner credentials are used. Coefficients are synthetic and RSA keys are generated during testing.

On 2026-11-03, a dedicated Windows Python 3.14 venv and an isolated source directory on Pi/Python 3.11 passed 29 onboarding, 13 relay and 11 firmware-tool tests. The Windows environment was created from the documented requirements. Tests did not change the production gateway or device enrollment.

- MQ bit/word ordering, invalid sizes, missing/duplicate/unknown/oversized APK members.
- Independently reproduced legacy v1 encryption, Unicode passphrases, tampering, wrong passwords and size limits.
- No overwrite, preservation of prior ciphertext, atomic-replacement failure, OS locking and POSIX mode 600.
- Simulated peer verification of AES challenges, bidirectional HMAC, RSA public keys/signatures and 20-byte GATT frames.
- Lost replies at each registration stage, wrong card proof and persistence failures; no automatic replacement keys or retry.
- ACK-only export refusal, read-only authentication, legacy-vault migration, verification-marker invalidation on failure, and minimal-field export.
- Zero/ambiguous advertisements, XIAO identity/cleanup, BLE cancellation cleanup, physical-preparation flags, refusal of visible getpass fallback and redaction of untrusted exception text.

Enrollment reuses only the public runtime's connection/framing path and calls read-only status for verification. It does not proceed to firmware, raw-memory or motor commands.

## Private archived-APK comparison

On 2026-11-03, memory-only coefficient extraction matched the original implementation. For nine synthetic inputs, MQ output matched both that implementation and emulation of the archived native processing. The APK, library, table and extracted output are not distributed. This comparison does not establish hardware enrollment success.
