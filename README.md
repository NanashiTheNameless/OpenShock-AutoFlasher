# OpenShock Auto-Flasher [![Ask DeepWiki](<https://deepwiki.com/badge.svg>)](<https://deepwiki.com/NanashiTheNameless/OpenShock-AutoFlasher>)

[![PyPI - Version](https://img.shields.io/pypi/v/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)
[![PyPI - Implementation](https://img.shields.io/pypi/implementation/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)
[![PyPI - Types](https://img.shields.io/pypi/types/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)

[![Tests](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/workflows/Tests/badge.svg)](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/actions/workflows/test.yml)
[![GitHub License](https://img.shields.io/github/license/NanashiTheNameless/OpenShock-AutoFlasher)](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/LICENSE)

Automatically flash OpenShock hubs as they are plugged in, verify firmware checksums,
and optionally test their WiFi AP and RF transmitter. Terminal colors show progress
and pass/fail results.

## Install

Requires Python 3.12+, pipx, and a USB connection to your hub. Runs on Linux,
macOS, and Windows.

```bash
pipx install --force 'git+https://github.com/NanashiTheNameless/OpenShock-AutoFlasher@main'
```

For PyPI or source installation, see the
[advanced guide](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#alternative-installation).

## Flash hubs

Start with hubs disconnected, run the command, then plug in a hub:

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32
```

The flasher processes each newly connected hub and waits for the next one.
Press Ctrl+C to stop. Replace the board name with yours; list available boards with:

```bash
OPSH-AutoFlash --help
```

Add `--erase` to clear flash first, `--alert` for a completion beep, or
`--channel beta` to use beta firmware.

## Test WiFi and RF

- **WiFi:** the host computer scans for the hub's exact
  `OpenShock-XX:XX:XX:XX:XX:XX` AP using its WiFi adapter. Scanning supports
  Linux, Windows, and macOS. See [platform requirements](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#wifi-ap-testing)
  for WiFi services and permissions.
- **RF:** prepare a separate USB tester with a 433 MHz receiver running
  [CaiXianlinRemoteIDMonitor](https://github.com/NanashiTheNameless/CaiXianlinRemoteIDMonitor).
  Follow the [tester setup guide](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#rf-tester-setup).

Start the command with hubs disconnected. **Plug the tester in first**, wait for
`RF tester detected ...; reserved for testing.`, then connect hubs one at a time.
Close other serial monitors before testing.

**Erase, flash, test, and factory-reset each hub:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --erase --alert \
  --test-wifi --test-rf --factory-reset-after-test
```

Factory reset clears saved hub settings after testing, whether tests pass or fail.
Omit `--factory-reset-after-test` to keep the settings after testing.

**Test existing firmware without flashing:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --test-only --test-wifi --test-rf
```

No hub port is required: test-only mode detects newly connected hubs and continues
after each result. Enable either WiFi or RF alone by omitting the other test flag.
RF testing checks Beep, Vibrate, and Stop with different IDs; Light and Shock are
not transmitted. Results appear in the terminal.

To process one already-connected hub and exit, add `--port /dev/ttyUSB1` (or a
Windows port such as `COM3`). For an explicit tester port, use
`--test-rf-port /dev/ttyUSB0` instead of `--test-rf`; the hub and tester must use
separate ports.

## Session report

One dark-mode HTML file records every hub attempt in the session, including MAC address,
USB serial number when available, flash status, and detailed test results.
The file is updated throughout the run, and its path is printed at startup.
Use `--report batch.html` to choose a filename, or `--no-report` to disable it.
See [report details](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#session-report).

## More information

See [README-advanced.md](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md) for all flags, firmware versions,
custom pins, WiFi scanning, RF validation, Linux permissions, troubleshooting,
and development instructions.

For contributions, see [CONTRIBUTING.md](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/CONTRIBUTING.md). Report vulnerabilities
using [SECURITY.md](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/SECURITY.md).

## License

Licensed under [GNU AGPL-3.0](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/LICENSE).

## Disclaimer

This tool is provided as-is. Use at your own risk. Always ensure you have backups of any important configurations before flashing firmware.

## Support My Work

If this project is useful to you, you can support it here:

- [<https://github.com/sponsors/NanashiTheNameless>](<https://github.com/sponsors/NanashiTheNameless>)
- [<https://buymeacoffee.com/NamelessNanashi>](<https://buymeacoffee.com/NamelessNanashi>)
- [<https://ko-fi.com/NanashiTheNameless>](<https://ko-fi.com/NanashiTheNameless>)
- [<https://liberapay.com/NamelessNanashi>](<https://liberapay.com/NamelessNanashi>)
- [<https://throne.com/NamelessNanashi>](<https://throne.com/NamelessNanashi>)
