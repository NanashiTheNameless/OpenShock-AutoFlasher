# OpenShock Auto-Flasher - Advanced Guide

See the [main README](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README.md) for installation and the common flash/test commands.

- [Alternative installation](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#alternative-installation)
- [Command-line options](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#command-line-options)
- [More examples](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#more-examples)
- [WiFi AP testing](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#wifi-ap-testing)
- [RF tester setup](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#rf-tester-setup)
- [RF command validation](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#rf-command-validation)
- [Connecting hubs and testers](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#connect-and-run)
- [Session report](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#session-report)
- [How it works](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#how-it-works)
- [Supported boards](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#supported-boards)
- [Linux permissions](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#permissions-linux)
- [Troubleshooting](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#troubleshooting)
- [Development](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#development)

## Alternative installation

### From PyPI

If you prefer a release from PyPI:

```bash
pipx install OpenShock-AutoFlasher
```

### From Source

1. Clone this repository:

```bash
git clone https://github.com/NanashiTheNameless/OpenShock-AutoFlasher.git
cd OpenShock-AutoFlasher
```

2. Create a virtual environment and install the command from this checkout:

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -e .
```

On Windows PowerShell, activate with `.venv\Scripts\Activate.ps1` instead.

## Command-Line Options

| Option         | Short | Description                                                    | Default  |
|----------------|-------|----------------------------------------------------------------|----------|
| `--channel`    | `-C`  | Firmware channel: `stable`, `beta`, or `develop`               | `stable` |
| `--version`    | `-V`  | Use specific firmware version (overrides channel)              | -        |
| `--board`      | `-B`  | Board type (required)                                          | -        |
| `--chip`       | -     | Target chip for esptool                                        | `auto`   |
| `--erase`      | `-E`  | Erase flash before flashing                                    | `false`  |
| `--no-auto`    | `-N`  | Disable auto-flash (just detect devices)                       | `false`  |
| `--post-flash` | `-P`  | Serial command to send after flashing (can use multiple times) | -        |
| `--post-flash-delay` | - | Milliseconds to wait between post-flash commands               | `0`      |
| `--alert`      | `-A`  | Beep after successful flashing or testing                           | `false`  |
| `--port` | - | Flash or test this serial port once and exit | - |
| `--report` | - | Filename for the single HTML session report | Timestamped filename |
| `--no-report` | - | Disable the session report | `false` |
| `--test-only` | - | Test newly connected hubs using existing firmware; requires a test | `false` |
| `--test-wifi` | - | Verify the hub broadcasts its OpenShock-MAC access point | `false` |
| `--test-wifi-ssid` | - | Explicit expected AP name; otherwise read hub MAC over USB | - |
| `--test-wifi-interface` | - | Adapter name on Linux/macOS, description on Windows | All adapters |
| `--test-wifi-scan-command` | - | Custom scan command as a JSON argument array | Automatic platform backend |
| `--test-rf` | - | Auto-detect the RF tester port by plugging the tester in first | `false` |
| `--test-rf-port` | - | Explicit serial port of the separate CaiXianlin RF monitor | - |
| `--test-timeout` | - | Timeout in seconds per test operation | `60` |
| `--factory-reset-after-test` | - | Send `factoryreset` after completed tests, whether they pass or fail | `false` |

## More examples

**Erase, flash, test WiFi and RF, then factory-reset each hub:**

Set up the separate
[CaiXianlinRemoteIDMonitor tester](https://github.com/NanashiTheNameless/CaiXianlinRemoteIDMonitor)
using the [RF tester setup guide below](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README-advanced.md#rf-tester-setup). Plug the tester in first,
wait for its detection message, then connect hubs one at a time.

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --erase --alert \
  --test-wifi --test-rf --factory-reset-after-test
```

This replaces manual `--post-flash 'rftransmit ...'` and
`--post-flash 'factoryreset'` commands. The RF test checks Beep, Vibrate, and Stop
with different IDs. Factory reset runs after testing, including when a test fails,
and clears saved hub settings. Omit `--factory-reset-after-test` to keep those settings.

**Flash with stable firmware:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32
```

**Test existing hubs as they are plugged in:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --test-only --test-wifi --test-rf
```

Plug the tester in first, then connect hubs one at a time. Add
`--factory-reset-after-test` if each hub should be reset after its tests.

**Flash with specific firmware version:**

```bash
OPSH-AutoFlash --version "<firmware-version>" --board Wemos-D1-Mini-ESP32
```

Replace `<firmware-version>` with the release you want to flash.

**Flash with beta firmware and erase existing data:**

```bash
OPSH-AutoFlash --channel beta --board Wemos-D1-Mini-ESP32 --erase
```

**Flash with an explicit esptool chip:**

```bash
OPSH-AutoFlash --board Seeed-Xiao-ESP32C3 --chip esp32c3 --erase
```

**Set a custom hub transmit pin before testing RF:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 \
  --post-flash "rftxpin 15" --test-rf
```

Use the GPIO wired to the hub's transmitter; `15` is only an example.
The tester's receive pin is configured separately in its own sketch.

**Use development firmware with audio alert:**

```bash
OPSH-AutoFlash --channel develop --board Wemos-D1-Mini-ESP32 --alert
```

**Detect devices without auto-flashing:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --no-auto
```

## Automated WiFi and RF testing

Enable either test independently, or both together. Tests run after flashing and
after any `--post-flash` commands. Green success and the completion alert require
all enabled tests to pass. In continuous mode, a failed device is reported and
the flasher continues waiting for the next device.

### WiFi AP testing

The WiFi test uses the **host computer's WiFi adapter** to confirm that the hub
broadcasts `OpenShock-XX:XX:XX:XX:XX:XX`. Enable it with `--test-wifi`.
The flasher reads the hub's base/STA MAC over USB using esptool, restarts the hub,
and scans for that exact SSID. A different nearby OpenShock hub cannot pass the
check. This leaves the hub's saved WiFi configuration unchanged and requires no
network credentials or association with the AP.

The scanner automatically chooses a backend. Platform-specific Python dependencies
are installed with Auto-Flasher:

| Platform | Backend | Requirements |
|----------|---------|--------------|
| Linux with `nmcli` and `busctl` | NetworkManager | Running NetworkManager, enabled WiFi adapter, permission to scan |
| Other Linux setups | `pywifi` | Running wpa_supplicant and access to its control socket |
| Windows | `pywifi`, with `comtypes` | WLAN AutoConfig service, enabled WiFi adapter, Location access where required |
| macOS | `pyobjc-framework-CoreWLAN` | Enabled WiFi adapter and Location Services permission for the terminal/Python app |

Select an adapter with `--test-wifi-interface wlan0` on Linux, `en0` on macOS,
or the adapter's description on Windows. Each backend requests a scan. NetworkManager
results must have a fresh `LastSeen`; the pywifi backends check wpa_supplicant BSS
age or Windows beacon timestamps because pywifi's ordinary result objects omit
freshness information. CoreWLAN uses a directed scan rather than its cached-results API.
Library scans run in a separate process so `--test-timeout` can stop a blocked call.

The hub must be in a state where its setup AP is enabled; saved configuration or
a backend connection may cause firmware to turn it off. A WiFi connection to the
hub is not required, and the scanner does not disconnect the host's existing network.

For an explicit AP name (or firmware with a customized MAC), use
`--test-wifi --test-wifi-ssid OpenShock-AA:BB:CC:DD:EE:FF`. This skips the USB MAC
read and its reboot. The SSID must be the specific hub's complete AP name.

To override the backend on any platform, supply your own scanner using
`--test-wifi-scan-command '["python", "scan_wifi.py"]'`. The command runs on the
host without a shell and must perform a **fresh WiFi scan**, exit successfully,
and print a JSON array of SSIDs, for example `["OpenShock-AA:BB:CC:DD:EE:FF"]`.
The adapter and any OS permissions are the custom scanner's responsibility;
returning cached network names can produce incorrect results. Malformed output,
command failure, and timeout fail the check. No scan command is needed for the
built-in scanners. `scan_wifi.py` is a user-provided script, not a bundled file.

API references: [pywifi](https://github.com/awkman/pywifi),
[CoreWLAN scans](<https://developer.apple.com/documentation/corewlan/cwinterface/scanfornetworks(withname:)>),
and [Windows WiFi location permissions](https://learn.microsoft.com/en-us/windows/win32/nativewifi/wi-fi-access-location-changes).

### RF tester setup

The tester is a **separate USB device** running
[CaiXianlinRemoteIDMonitor](https://github.com/NanashiTheNameless/CaiXianlinRemoteIDMonitor).
Auto-Flasher flashes the OpenShock hubs; prepare the tester separately:

1. Get the monitor sketch from the
   [monitor repository and setup instructions](https://github.com/NanashiTheNameless/CaiXianlinRemoteIDMonitor#usage).
   Use the updated receiver decoder with the signed buffer-index fix.
2. Connect a 433 MHz receiver to the tester. Match its signal wire to `rx_pin` in
   [CaiXianlinRemoteIDMonitor.ino](https://github.com/NanashiTheNameless/CaiXianlinRemoteIDMonitor/blob/main/CaiXianlinRemoteIDMonitor.ino);
   check the sketch's value instead of assuming a fixed pin number.
3. Upload that sketch to the tester using your board's Arduino workflow.
   Its serial output must use 115200 baud and the standard format, for example:

   ```text
   ID: 0x2E16 (11798) | Channel: 1 | Mode: Beep
   ```

4. Close the tester's serial monitor before running Auto-Flasher so it can read
   the tester port. Keep the tester connected during the hub tests.
5. Connect the hub's RF transmitter to its configured transmit pin. For a custom
   pin, add a post-flash command such as `--post-flash "rftxpin 15"` when flashing.

### RF command validation

The RF test sends three CaiXianlin commands, each with a different randomly
selected nonzero ID:

| Command | Intensity sent | Duration | Expected monitor mode |
|---------|----------------|----------|-----------------------|
| Beep | 0 | 1 second | `Beep` |
| Vibrate | 1 | 1 second | `Vibrate` |
| Stop | 0 | 300 milliseconds | `Stop` |

Every command must match its own ID, displayed channel 1, and expected mode.
Each has a separate pass/fail line, and remaining commands are attempted even if
an earlier command fails. The test discards old serial data and waits for each
burst and the monitor's debounce interval before sending the next command.
The tester is read asynchronously starting before transmission, capturing immediate
broadcasts even while the hub's serial acknowledgement is pending.
A transmit acknowledgement alone does not pass the test. No paired collar is
needed. The monitor's current output verifies ID/channel/mode, but does not expose
numeric intensity or measure RF power/range. Light and Shock are not transmitted.
Firmware emergency-stop rejection fails the test normally.

Add `--factory-reset-after-test` to send the hub's `factoryreset` serial command
once all enabled tests have finished, whether they pass or fail. This clears saved
hub settings, including settings supplied through post-flash commands, and restarts
the hub. The flasher requires the firmware's reset/restart messages and a serial
response after reboot before reporting reset success. Test failures remain failures
even if reset succeeds; reset failure also fails the run. The flag requires at
least one test and also works with `--test-only`. It is off by default and is not
run when flashing fails before testing or when the run is interrupted.

### Connect and run

Use `--test-rf` to select the tester port automatically:

1. Start the flasher with the hubs disconnected. Use `--test-only` to test their
   existing firmware instead of flashing them.
2. Plug in the RF tester first. It can also already be connected if it is the only
   serial device present. Wait for `RF tester detected ...; reserved for testing.`
3. Leave the tester connected and plug in hubs to process.

Selection uses connection order. If multiple serial ports are already present or
arrive together, the flasher waits for you to unplug and reconnect only the tester.
With `--port`, the specified hub port is excluded from tester selection.
Alternatively, use `--test-rf-port PORT` to select the tester explicitly; this
cannot be combined with `--test-rf`.

The selected tester is excluded from flashing. If an automatically selected tester
has a unique USB serial number, the flasher follows it when it reconnects on a new
port. Without a USB serial number, keep its port stable or restart the flasher to
select it again. Close other serial terminals during testing. For explicit selection
on Linux, a `/dev/serial/by-id/...` path is useful for keeping its identity stable.
The hub must return on the supplied port after reboot.

Flash and test each newly connected hub, with an audible alert and factory reset:

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --erase --alert \
  --test-wifi --test-rf --factory-reset-after-test
```

Flash and test one hub with explicit ports. In these examples, `/dev/ttyUSB0` is
the tester and `/dev/ttyUSB1` is the hub; replace them with your actual ports:

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --port /dev/ttyUSB1 --erase --alert \
  --test-wifi --test-rf-port /dev/ttyUSB0 --factory-reset-after-test
```

Test already-flashed hubs as they are plugged in:

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --test-only --test-wifi --test-rf
```

`--test-only` needs no hub port. It waits for newly connected hubs, tests each one,
and continues after a pass or failure. It skips firmware lookup, download, erase,
flashing, and post-flash commands. Factory reset runs only when
`--factory-reset-after-test` is also supplied. Start with hubs disconnected, just
as for continuous flashing; for RF, connect the tester first.

To test one already-connected hub and exit, add `--port`:

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --port /dev/ttyUSB1 --test-only \
  --test-wifi --test-rf-port /dev/ttyUSB0
```

Retest only RF, or only the WiFi AP:

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --test-only --test-rf

OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --test-only --test-wifi
```

On Windows, use port names such as `COM3` and `COM4`. Omit `--test-only` to flash
the explicit port first. Single-device runs exit with **0** on success, **1** on
flash/test failure, and **2** for invalid arguments. `--no-auto` cannot be
combined with hardware tests or an explicit port.

Test results appear in the terminal, including pass/fail and failure details for
each enabled check. RF progress distinguishes the hub acknowledgement from waiting
for the tester, with updates every five seconds and separate errors for a silent
tester, unrecognized serial output, or mismatched frames. Reception timeouts with
unrecognized output show the tester's first 256 bytes; up to five
unrecognized lines per case are also printed as they arrive. Control characters
are escaped to keep boot/error messages and garbled data readable. RF acknowledgement
waits at most five seconds. `--test-timeout` bounds individual connection, response,
and reception operations; USB MAC detection and device startup are additional to the
WiFi scan timeout.

The RF check uses OpenShock's automated `$sysinfo` and `$rftransmit` serial commands
and `$SYS$` responses. Optional factory reset sends `$factoryreset` and checks its
plain-text reset/restart messages. Firmware that lacks these commands or has serial input
disabled fails the RF test instead of being assumed functional.

## Session report

By default, one `OpenShock-session-<timestamp>-<id>.html` file is created in the
current directory for each flashing or test-only session. The terminal prints its
absolute path. Choose a path with `--report batch.html`, or disable reporting with
`--no-report`. Detection-only mode (`--no-auto`) does not create a report.
An existing report file is never overwritten by a new session; choose a new name.

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --erase --alert \
  --test-wifi --test-rf --factory-reset-after-test --report batch.html
```

Each hub connection attempt gets a record containing:

- Port, board, MAC address and its source, detected chip, and USB metadata.
- USB adapter serial number when available. This is not a separate ESP32 serial
  number; the MAC identifies the chip. Missing identity fields say `Unavailable`.
- Firmware version being flashed, SHA256, and file size. Existing firmware's
  version is left unavailable in test-only mode.
- Download, erase, flash, and post-flash command status, plus recorded stub retries.
- WiFi AP, RF, and factory-reset results with durations and failure details.
- Every attempted RF command's ID, channel, mode, intensity, duration, and result.
- Start/end times in UTC, elapsed time, overall outcome, warnings, and errors.

MAC/chip details are captured from esptool's normal output while flashing. The
WiFi test also supplies the MAC it reads from the hub. Test-only runs without that
MAC read attempt a separate USB identity read, which restarts the hub; failure to
read identity is recorded as a warning and does not invent a MAC or serial number.
The report stores command counts and outcomes rather than raw post-flash commands
or their responses, which can contain credentials.

The same file is updated atomically as each stage or test finishes. Completed
records survive later failures or Ctrl+C. Pressing Ctrl+C while waiting for another
hub ends the session as `completed`, preserving each device's pass or fail result.
Stopping during a flash or test marks that device and the session as `interrupted`.
A forced process kill can leave its last saved state as `in_progress`.
Reconnecting the same hub creates another attempt, preserving its earlier result.
The tester is not included as a flashed hub. Flash success remains separate from
test failure, and disabled or unattempted tests are never counted as passes.

The HTML uses a dark theme with color-coded status labels. It is self-contained
and can be opened locally without network access.

## How It Works

Terminal backgrounds indicate status: blue means waiting, yellow means flashing
or testing, green means success, and red means an error.

1. **Fetches** the latest firmware version from firmware.openshock.org (or uses specified version)
2. **Validates** the specified board type against available boards
3. **Initializes** known USB ports and begins monitoring
4. **Detects** when new devices are connected
5. **Downloads** firmware binary and checksum in parallel
6. **Verifies** firmware integrity using SHA256 checksum
7. **Optionally erases** flash memory (if `--erase` is specified)
8. **Flashes** the device using esptool
9. **Executes** post-flash commands over serial (if specified)
10. **Tests** WiFi and/or RF and displays results (if enabled)
11. **Repeats** for additional devices (continuous mode), or exits for `--port`

The tool uses esptool with optimized settings and can send serial commands to the device after flashing for automated configuration or testing.

With `--test-only`, it detects and tests hubs without the firmware lookup or
flashing steps. `--port` selects a single hub in either mode; without it, the tool
keeps waiting for newly connected hubs until you press Ctrl+C.

## Supported Boards

The tool supports multiple ESP32-based boards. To view the current list of available boards, run:

```bash
OPSH-AutoFlash --help                        # Stable channel boards
OPSH-AutoFlash --channel beta --help         # Beta channel boards
OPSH-AutoFlash -C develop --help             # Develop channel boards
```

Common board types include:

- `Wemos-D1-Mini-ESP32`
- `Wemos-Lolin-S2-Mini`
- `Wemos-Lolin-S3`
- `Wemos-Lolin-S3-Mini`
- `Waveshare_esp32_s3_zero`
- `Pishock-2023`
- `Pishock-Lite-2021`
- `Seeed-Xiao-ESP32C3`
- `Seeed-Xiao-ESP32S3`
- `DFRobot-Firebeetle2-ESP32E`
- `OpenShock-Core-V1`
- `OpenShock-Core-V2`
- `NodeMCU-32S`

**Note:** Different channels may have different board support. Always check the help output for your selected channel.

## Permissions (Linux)

On Linux, you may need to add your user to the `dialout` group to access serial ports:

```bash
sudo usermod -a -G dialout $USER
```

Then log out and log back in for the changes to take effect.

## Troubleshooting

**Device not detected:**

- Ensure the device is in bootloader mode
- Check USB cable connection
- Verify device appears in system (check `dmesg` on Linux or Device Manager on Windows)

**Permission errors:**

- Add user to dialout/uucp group (Linux)
- Run with appropriate permissions
- Check USB cable supports data transfer (not charge-only)

**Verification fails:**

- Try using `--erase` flag to erase flash first
- Check for hardware issues
- Try a different USB port or cable

**Failed to start stub flasher:**

The flasher reconnects and retries at 57600 baud when the stub fails to start.
Erase allows a second retry at 9600 baud. These rates slow the initial stub upload
as well as the operation itself. If retries fail, close other serial tools,
power-cycle the hub, and check its USB cable and power supply. See
[esptool troubleshooting](https://docs.espressif.com/projects/esptool/en/latest/esp32/troubleshooting.html).

## Development

### Running Tests

The project includes a comprehensive test suite using pytest. To run the tests:

1. Install development dependencies:

```bash
python -m pip install -e ".[dev]"
```

1. Run the test suite:

```bash
pytest tests/ -v
```

1. Run tests with coverage:

```bash
pytest tests/ -v --cov=openshock_autoflasher --cov-report=term-missing
```

### Code Quality

The project uses several tools for code quality:

- **Black** - Code formatting
- **Flake8** - Linting
- **Mypy** - Type checking

Run code quality checks:

```bash
# Format code
black openshock_autoflasher/ tests/

# Lint code
flake8 openshock_autoflasher/ tests/

# Type check
mypy openshock_autoflasher/
```

### Project Structure

The codebase is modular and organized as follows:

- `openshock_autoflasher/` - Main package
  - `constants.py` - Configuration constants
  - `styles.py` - Terminal styling and colors
  - `flasher.py` - Core AutoFlasher class with flashing logic
  - `hardware_tests.py` - WiFi/RF test orchestration and serial checks
  - `wifi.py` - Host WiFi scanning and hub AP identification
  - `wifi_native.py` - Native WiFi library scanning in a bounded subprocess
  - `report.py` - One HTML report for all devices in a session
  - `cli.py` - Command-line interface and argument parsing
  - `__init__.py` - Package initialization
  - `__main__.py` - Module entry point
- `tests/` - Test suite
  - `test_constants.py` - Tests for constants module
  - `test_styles.py` - Tests for styles module
  - `test_flasher.py` - Tests for flasher module
  - `test_cli.py` - Tests for CLI module
  - `test_hardware_tests.py` - Serial protocol and hardware-test regressions
  - `test_wifi.py` - Host WiFi scanner tests
  - `test_wifi_native.py` - Native WiFi scanner tests
  - `test_report.py` - Session report and device recording tests

### Continuous Integration

The project uses GitHub Actions for CI/CD:

- **Tests Workflow** - Runs tests on Ubuntu, Windows, and macOS with Python 3.12-3.14
- **Publish Workflow** - Publishes to PyPI on release

[Back to the main README](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/README.md).
