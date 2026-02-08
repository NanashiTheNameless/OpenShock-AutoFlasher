# OpenShock Auto-Flasher

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
- **Parallel downloads** for faster firmware retrieval
- **Continuous mode** - flash multiple devices in sequence
- **Optional flash erase** before flashing
- **Smart text wrapping** - Long messages wrap cleanly without cutting words
- **Dynamic boards list** - View available boards for any channel via `--help`

## Requirements

- Python 3.6 or higher
- Linux, macOS, or Windows
- USB connection to ESP32 devices

## Installation

1. Clone this repository:

```bash
git clone https://github.com/NanashiTheNameless/OpenShock-AutoFlasher.git
cd OpenShock-AutoFlasher
```

2. Install dependencies:

```bash
pip3 install -r requirements.txt
```

## Usage

### Basic Usage

Flash devices using the stable firmware channel:

```bash
python3 AutoFlash.py --board <board-name>
```

**To see available boards for a specific channel:**

```bash
python3 AutoFlash.py --help                    # Shows boards for stable channel
python3 AutoFlash.py --channel beta --help     # Shows boards for beta channel
python3 AutoFlash.py -c develop --help         # Shows boards for develop channel
```

### Command-Line Options

| Option      | Short | Description                                      | Default  |
|-------------|-------|--------------------------------------------------|----------|
| `--channel` | `-c`  | Firmware channel: `stable`, `beta`, or `develop` | `stable` |
| `--board`   | `-b`  | Board type (required)                            | -        |
| `--erase`   | `-e`  | Erase flash before flashing                      | `false`  |
| `--no-auto` | `-n`  | Disable auto-flash (just detect devices)         | `false`  |

### Examples

**Flash with stable firmware:**

```bash
python3 AutoFlash.py --board Wemos-D1-Mini-ESP32
```

**Flash with beta firmware and erase existing data:**

```bash
python3 AutoFlash.py --channel beta --board Wemos-D1-Mini-ESP32 --erase
```

**Use development firmware:**

```bash
python3 AutoFlash.py --channel develop --board Wemos-D1-Mini-ESP32
```

**Detect devices without auto-flashing:**

```bash
python3 AutoFlash.py --board Wemos-D1-Mini-ESP32 --no-auto
```

## How It Works

1. **Fetches** the latest firmware version from firmware.openshock.org
2. **Validates** the specified board type
3. **Monitors** USB ports for newly connected devices
4. **Downloads** firmware binary and checksum in parallel
5. **Verifies** firmware integrity using SHA256
6. **Flashes** the device using esptool
7. **Verifies** the flash was successful
8. **Repeats** for additional devices (continuous mode)

The tool uses esptool with optimized settings:
 from firmware.openshock.org.

**To view the current list of available boards, run:**

```bash
python3 AutoFlash.py --help                    # Stable channel boards
python3 AutoFlash.py --channel beta --help     # Beta channel boards
python3 AutoFlash.py -c develop --help         # Develop channel boards
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

**Note:** Different channels may have different board support. Always check the help output
- `Pishock-Lite-2021`
- `Seeed-Xiao-ESP32C3`
- `Seeed-Xiao-ESP32S3`
- `DFRobot-Firebeetle2-ESP32E`
- `OpenShock-Core-V1`
- `OpenShock-Core-V2`

Run the tool to see the current available boards for your selected channel.

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

## License

See [LICENSE](LICENSE) file for details.

## Contributing

Contributions are welcome! Please feel free to submit issues or pull requests.

## Disclaimer

This tool is provided as-is. Use at your own risk. Always ensure you have backups of any important configurations before flashing firmware.
