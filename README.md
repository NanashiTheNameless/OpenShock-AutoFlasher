# OpenShock Auto-Flasher [![Ask DeepWiki](<https://deepwiki.com/badge.svg>)](<https://deepwiki.com/NanashiTheNameless/OpenShock-AutoFlasher>)

[![PyPI - Version](https://img.shields.io/pypi/v/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)
[![PyPI - Python Version](https://img.shields.io/pypi/pyversions/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)
[![PyPI - Implementation](https://img.shields.io/pypi/implementation/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)
[![PyPI - Types](https://img.shields.io/pypi/types/OpenShock-AutoFlasher)](https://pypi.org/project/OpenShock-AutoFlasher/)

[![Tests](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/workflows/Tests/badge.svg)](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/actions/workflows/test.yml)
[![GitHub License](https://img.shields.io/github/license/NanashiTheNameless/OpenShock-AutoFlasher)](https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/LICENSE)

Automatically flash OpenShock firmware to ESP32 devices when they are plugged in. Features color-coded terminal backgrounds to indicate the current status at a glance.

## Features

- **Automatic detection** of newly connected devices
- **Color-coded status** with background colors:
  - **Blue** - Waiting for device
  - **Yellow** - Flashing in progress
  - **Green** - Flash complete
  - **Red** - Error occurred
- **Firmware verification** using SHA256 checksums
- **Multiple channels** - stable, beta, or develop
- **Post-flash commands** - Send serial commands to device after flashing
- **Continuous mode** - flash multiple devices in sequence
- **Optional flash erase** before flashing
- **Smart text wrapping** - Long messages wrap cleanly without cutting words
- **Dynamic boards list** - View available boards for any channel via `--help`

## Requirements

- Python 3.12 or higher
- Linux, macOS, or Windows
- USB connection to ESP32 devices

## Installation

### From GitHub with pipx (Recommended)

Install directly from the latest GitHub version:

```bash
pipx install --force 'git+https://github.com/NanashiTheNameless/OpenShock-AutoFlasher@main'
```

This makes the `OPSH-AutoFlash` command available system-wide.

### Alternative: From PyPI

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

1. Install dependencies:

```bash
pip3 install -r requirements.txt
```

## Usage

### Basic Usage

Flash devices using the stable firmware channel:

```bash
OPSH-AutoFlash --board <board-name>
```

View available boards for different channels:

```bash
OPSH-AutoFlash --help                        # Shows boards for stable channel
OPSH-AutoFlash --channel beta --help         # Shows boards for beta channel
OPSH-AutoFlash -C develop --help             # Shows boards for develop channel
```

### Command-Line Options

| Option         | Short | Description                                                    | Default  |
|----------------|-------|----------------------------------------------------------------|----------|
| `--channel`    | `-C`  | Firmware channel: `stable`, `beta`, or `develop`               | `stable` |
| `--version`    | `-V`  | Use specific firmware version (overrides channel)              | -        |
| `--board`      | `-B`  | Board type (required)                                          | -        |
| `--erase`      | `-E`  | Erase flash before flashing                                    | `false`  |
| `--no-auto`    | `-N`  | Disable auto-flash (just detect devices)                       | `false`  |
| `--post-flash` | `-P`  | Serial command to send after flashing (can use multiple times) | -        |
| `--alert`      | `-A`  | Beep audibly when flashing completes                           | `false`  |

### Examples

**Flash with stable firmware:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32
```

**Flash with specific firmware version:**

```bash
OPSH-AutoFlash --version 1.5.0 --board Wemos-D1-Mini-ESP32
```

**Flash with beta firmware and erase existing data:**

```bash
OPSH-AutoFlash --channel beta --board Wemos-D1-Mini-ESP32 --erase
```

**Flash and send post-flash commands to device:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 \
  --post-flash "help" \
  --post-flash "version" \
  --post-flash "status"
```

**Use development firmware with audio alert:**

```bash
OPSH-AutoFlash --channel develop --board Wemos-D1-Mini-ESP32 --alert
```

**Detect devices without auto-flashing:**

```bash
OPSH-AutoFlash --board Wemos-D1-Mini-ESP32 --no-auto
```

## How It Works

1. **Fetches** the latest firmware version from firmware.openshock.org (or uses specified version)
2. **Validates** the specified board type against available boards
3. **Initializes** known USB ports and begins monitoring
4. **Detects** when new devices are connected
5. **Downloads** firmware binary and checksum in parallel
6. **Verifies** firmware integrity using SHA256 checksum
7. **Optionally erases** flash memory (if `--erase` is specified)
8. **Flashes** the device using esptool
9. **Executes** post-flash commands over serial (if specified)
10. **Repeats** for additional devices (continuous mode)

The tool uses esptool with optimized settings and can send serial commands to the device after flashing for automated configuration or testing.

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

## Development

### Running Tests

The project includes a comprehensive test suite using pytest. To run the tests:

1. Install development dependencies:

```bash
pip install -e .[dev]
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
  - `cli.py` - Command-line interface and argument parsing
  - `__init__.py` - Package initialization
  - `__main__.py` - Module entry point
- `tests/` - Test suite
  - `test_constants.py` - Tests for constants module
  - `test_styles.py` - Tests for styles module
  - `test_flasher.py` - Tests for flasher module
  - `test_cli.py` - Tests for CLI module

### Continuous Integration

The project uses GitHub Actions for CI/CD:

- **Tests Workflow** - Runs tests on Ubuntu, Windows, and macOS with Python 3.12-3.14
- **Publish Workflow** - Publishes to PyPI on release

## License

This project is licensed under the GNU Affero General Public License v3.0 (AGPL-3.0). See [LICENSE](<https://github.com/NanashiTheNameless/OpenShock-AutoFlasher/blob/main/LICENSE>)) file for details.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Disclaimer

This tool is provided as-is. Use at your own risk. Always ensure you have backups of any important configurations before flashing firmware.
