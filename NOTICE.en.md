# Distribution scope and third-party rights

[日本語](NOTICE.md) | English

[SOURCES.en.md](SOURCES.en.md) records prior research, reference material, libraries, and the parts implemented by this project. Some behavior was reimplemented by inspecting the old application; this is not a claim of clean-room development.

The included MIT License applies to this project's original code, patches, tests, and documentation, including the C3 UART sketch, host recovery code, incident report, onboarding tools, protocol implementation and ESPHome configuration. It does not grant rights over third-party software or reference data. This project is not an official or certified distribution from Qrio, Sony, Broadcom, Cypress, Infineon, Apple, or the other named organizations.

The following are not included:

- Complete stock firmware, EEPROM/ROM dumps, SDKs or archived official application APKs.
- Owner cards, serial numbers, owner private keys, recovery passphrases or HomeKit pairing secrets.
- Source or photographs copied from upstream qriohack.
- Dependency source distributions, wheels or native executables.
- Device backups, failed SEC001 deployment images or unprocessed private logs.

The incident evidence file is a curated summary with device-specific information removed. It is not a distribution of the original reports or dumps.

MQ enrollment coefficients are read in memory from the supported APK supplied by the user. The APK, `libmq.so`, and the coefficient table are not distributed, installed, executed or automatically downloaded. This project's MIT license does not provide redistribution permission for those files.

We have not established permission to redistribute stock firmware. The firmware kit therefore provides 248 bytes of original replacements, source fingerprints, and application tools; users supply their own locally acquired stock data. Generated firmware and device backups may contain third-party stock code. Do not add them or `.private` to a redistribution.

ESPHome, aioesphomeapi, Arduino/ESP32 Core, pyserial, pyelftools, Bleak, dbus-fast, cryptography and other dependencies retain their respective licenses and are obtained separately. Version pins are in the relevant `requirements*.txt` files. The original release ZIP bundles no dependencies; initial setup needs Internet access.

Generated XIAO firmware contains Wi-Fi credentials and an API key and must remain private. MIT licensing of the configuration does not override dependency licensing or make secrets suitable for publication.

References: [MIT License](https://opensource.org/license/mit), [GitHub licensing documentation](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/customizing-your-repository/licensing-a-repository).
