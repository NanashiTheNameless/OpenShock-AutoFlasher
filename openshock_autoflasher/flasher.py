"""
Core flashing logic for OpenShock Auto-Flasher
"""

import hashlib
import tempfile
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Optional, List, Set

import esptool
import esptool.util
import requests
import serial
import serial.tools.list_ports
from rich.style import Style
from .constants import (
    REQUEST_TIMEOUT,
    BASE_URL,
    BAUD_RATE,
    FLASH_MODE,
    FLASH_FREQ,
    FLASH_ADDRESS,
    INITIAL_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    POLL_BACKOFF_THRESHOLD,
    DEVICE_INIT_DELAY,
)
from .styles import StateColors, console


class AutoFlasher:
    """Main auto-flashing controller for OpenShock devices"""

    def __init__(
        self,
        channel: str = "stable",
        board: Optional[str] = None,
        erase_flash: bool = False,
        auto_flash: bool = True,
        post_flash_commands: Optional[List[str]] = None,
    ) -> None:
        self.channel: str = channel
        self.board: Optional[str] = board
        self.erase_flash: bool = erase_flash
        self.auto_flash: bool = auto_flash
        self.post_flash_commands: List[str] = post_flash_commands or []
        self.base_url: str = BASE_URL
        self.known_ports: Set[str] = set()
        self.state: str = "waiting"
        self.current_style: Style = StateColors.WAITING
        # Cache version to avoid refetching
        self.version_cache: Optional[str] = None
        # Cache boards list
        self.boards_cache: Optional[List[str]] = None

    def get_style(self) -> Style:
        """Get style based on current state"""
        styles = {
            "waiting": StateColors.WAITING,
            "flashing": StateColors.FLASHING,
            "done": StateColors.DONE,
            "error": StateColors.ERROR,
        }
        return styles.get(self.state, StateColors.WAITING)

    def set_state(self, state: str) -> None:
        """Change state and update terminal background"""
        self.state = state
        self.current_style = self.get_style()

    def log(self, message: str) -> None:
        """Print log message with current background"""
        timestamp = time.strftime("%H:%M:%S")
        # Fill entire width with background color
        max_len = console.width - 2
        text = f"[{timestamp}] {message}"

        # Wrap text if it's too long
        if len(text) > max_len:
            # Wrap the text, preserving words
            wrapped_lines = textwrap.wrap(
                text,
                width=max_len,
                break_long_words=False,
                break_on_hyphens=False,
            )
            for line in wrapped_lines:
                padding = " " * (max_len - len(line))
                console.print(
                    f"{line}{padding}",
                    style=self.current_style,
                    markup=False,
                    highlight=False,
                )
        else:
            padding = " " * (max_len - len(text))
            console.print(
                f"{text}{padding}",
                style=self.current_style,
                markup=False,
                highlight=False,
            )

    def fetch_version(self) -> str:
        """Fetch latest version for the selected channel (cached)"""
        if self.version_cache:
            return self.version_cache
        url = f"{self.base_url}/version-{self.channel}.txt"
        self.log(f"Fetching version from {self.channel} channel...")
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        self.version_cache = response.text.strip()
        self.log(f"Latest {self.channel} version: {self.version_cache}")
        return self.version_cache

    def fetch_boards(self, version: str) -> List[str]:
        """Fetch available boards for a version (cached)"""
        if self.boards_cache:
            return self.boards_cache
        url = f"{self.base_url}/{version}/boards.txt"
        self.log("Fetching available boards...")
        response = requests.get(url, timeout=REQUEST_TIMEOUT)
        response.raise_for_status()
        self.boards_cache = [line.strip() for line in response.text.strip().split("\n")]
        self.log(f"Available boards: {', '.join(self.boards_cache)}")
        return self.boards_cache

    def download_firmware(self, version: str, board: str) -> bytes:
        """Download and verify firmware binary with progress"""
        self.log(f"Downloading firmware for {board}...")

        firmware_url = f"{self.base_url}/{version}/{board}/firmware.bin"
        hash_url = f"{self.base_url}/{version}/{board}/hashes.sha256.txt"

        # Parallel download of firmware and hash
        def download_firmware_data():
            response = requests.get(firmware_url, stream=True, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.content

        def download_hash_data():
            response = requests.get(hash_url, timeout=REQUEST_TIMEOUT)
            response.raise_for_status()
            return response.text

        # Use thread pool to download in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            firmware_future = executor.submit(download_firmware_data)
            hash_future = executor.submit(download_hash_data)

            firmware_data = firmware_future.result()
            hash_text = hash_future.result()

        # Parse hash file
        expected_hash = None
        for line in hash_text.strip().split("\n"):
            parts = line.split()
            if len(parts) >= 2:
                hash_val = parts[0].strip()
                filename = " ".join(parts[1:]).strip()
                if filename in ["firmware.bin", "./firmware.bin"]:
                    expected_hash = hash_val
                    break

        if not expected_hash:
            raise ValueError("Could not find hash for firmware.bin")

        # Verify hash (case-insensitive comparison)
        calculated_hash = hashlib.sha256(firmware_data).hexdigest().lower()
        if calculated_hash != expected_hash.lower():
            raise ValueError(f"Hash mismatch! Expected {expected_hash}, " f"got {calculated_hash}")

        size_bytes = len(firmware_data)
        self.log(f"✓ Firmware downloaded and verified ({size_bytes} bytes)")
        return firmware_data

    def execute_post_flash_commands(self, port: str) -> None:
        """Execute post-flash commands over serial connection"""
        try:
            self.log("")
            self.log("=" * 60)
            cmd_count = len(self.post_flash_commands)
            self.log(f"Executing {cmd_count} post-flash command(s)...")
            self.log("=" * 60)

            # Open serial connection
            # Give device time to reboot after flash
            time.sleep(2)

            ser = serial.Serial(port, 115200, timeout=2)
            time.sleep(0.5)  # Allow connection to stabilize

            # Clear any buffered data
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            cmd_total = len(self.post_flash_commands)
            for i, cmd in enumerate(self.post_flash_commands, 1):
                self.log(f"[{i}/{cmd_total}] Sending: {cmd}")

                # Send command with newline
                ser.write((cmd + "\n").encode("utf-8"))
                ser.flush()

                # Wait a bit for command to execute
                time.sleep(0.5)

                # Read any response
                if ser.in_waiting > 0:
                    response = ser.read(ser.in_waiting).decode("utf-8", errors="ignore").strip()
                    if response:
                        self.log(f"Response: {response}")

            ser.close()
            self.log("✓ Post-flash commands completed")
            self.log("=" * 60)

        except Exception as e:
            self.log(f"⚠ Warning: Post-flash command execution failed: {e}")
            self.log("Continuing anyway...")

    def flash_device(self, port: str, version: str, board: str) -> None:
        """Flash firmware to device"""
        temp_firmware: Optional[Path] = None
        try:
            self.set_state("flashing")
            self.log("=" * 60)
            self.log(f"Starting flash process for {board}")
            self.log(f"Port: {port}")
            self.log(f"Version: {version}")
            self.log("=" * 60)

            # Download firmware
            firmware_data = self.download_firmware(version, board)

            # Save firmware to temporary file
            temp_file = tempfile.NamedTemporaryFile(
                mode="wb",
                suffix=".bin",
                prefix="OpenShock_Firmware_",
                delete=False,
            )
            temp_firmware = Path(temp_file.name)
            temp_file.write(firmware_data)
            temp_file.flush()
            temp_file.close()

            # Prepare esptool arguments
            args = [
                "--port",
                port,
                "--baud",
                BAUD_RATE,
                "--chip",
                "auto",
                "write-flash",
            ]

            if self.erase_flash:
                self.log("Erasing flash...")
                erase_args = [
                    "--port",
                    port,
                    "--baud",
                    BAUD_RATE,
                    "erase-flash",
                ]

                try:
                    esptool.main(erase_args)
                except (SystemExit, esptool.util.FatalError) as e:
                    if isinstance(e, SystemExit) and e.code == 0:
                        pass
                    else:
                        raise Exception(f"Erase failed: {e}")

                self.log("✓ Erase complete")

            args.extend(
                [
                    "--flash-mode",
                    FLASH_MODE,
                    "--flash-freq",
                    FLASH_FREQ,
                    "--flash-size",
                    "detect",
                    FLASH_ADDRESS,
                    str(temp_firmware),
                ]
            )

            self.log("Flashing firmware...")

            try:
                esptool.main(args)
            except (SystemExit, esptool.util.FatalError) as e:
                if isinstance(e, SystemExit) and e.code == 0:
                    pass
                else:
                    raise Exception(f"Flash failed: {e}")

            # Execute post-flash commands if any
            if self.post_flash_commands:
                self.execute_post_flash_commands(port)

            self.set_state("done")
            self.log("✓ Flashing complete!")
            self.log("=" * 60)
            self.log("SUCCESS! Device flashed successfully")
            self.log("=" * 60)

            # Cleanup
            temp_firmware.unlink(missing_ok=True)

        except Exception as e:
            self.set_state("error")
            if temp_firmware:
                temp_firmware.unlink(missing_ok=True)
            self.log(f"✗ Error during flashing: {e}")
            raise

    def detect_new_port(self) -> Optional[List[str]]:
        """Detect when a new serial port is connected"""
        try:
            current_ports = set([p.device for p in serial.tools.list_ports.comports()])
            new_ports = current_ports - self.known_ports

            if new_ports:
                self.known_ports = current_ports
                # Return all new ports, not just the first
                return list(new_ports)

            self.known_ports = current_ports
        except Exception as e:
            # Log port detection errors instead of silently ignoring
            self.log(f"⚠ Warning: Port detection error: {e}")
        return None

    def run(self) -> None:
        """Main run loop"""
        self.set_state("waiting")

        # Print header with background
        self.log("OpenShock Auto-Flasher")
        self.log("=" * 60)
        self.log(f"Channel: {self.channel}")
        self.log(f"Erase flash: {self.erase_flash}")
        self.log(f"Auto-flash: {self.auto_flash}")
        self.log("=" * 60)
        self.log("")

        # Fetch version and boards
        try:
            version = self.fetch_version()
            boards = self.fetch_boards(version)

            # Early validation: check board exists before waiting
            if self.board not in boards:
                self.set_state("error")
                self.log(f"Error: Board '{self.board}' not found " "in available boards")
                self.log(f"Available boards: {', '.join(boards)}")
                return

        except Exception as e:
            self.set_state("error")
            self.log(f"Error fetching firmware info: {e}")
            return

        # Initialize known ports
        self.known_ports = set([p.device for p in serial.tools.list_ports.comports()])

        self.set_state("waiting")
        self.log("Waiting for device to be plugged in...")
        self.log("(Press Ctrl+C to exit)")

        try:
            # Adaptive polling: start with 0.5s, back off to 1s if no activity
            poll_interval = INITIAL_POLL_INTERVAL
            consecutive_checks = 0

            while True:
                new_ports = self.detect_new_port()

                if new_ports:
                    # Process all newly detected ports
                    for new_port in new_ports:
                        self.log(f"✓ Device detected on {new_port}")
                        # Reset to fast polling after device detected
                        poll_interval = INITIAL_POLL_INTERVAL
                        consecutive_checks = 0

                        if self.auto_flash:
                            # Give device time to initialize
                            time.sleep(DEVICE_INIT_DELAY)
                            self.flash_device(new_port, version, self.board)

                            if self.auto_flash:
                                self.log("")
                                self.set_state("waiting")
                                self.log("Waiting for next device...")
                                self.log("(Press Ctrl+C to exit)")
                                self.log("")
                        else:
                            self.log("Auto-flash disabled. Skipping...")
                else:
                    # Gradually increase polling interval if no activity
                    consecutive_checks += 1
                    if consecutive_checks > POLL_BACKOFF_THRESHOLD:
                        poll_interval = min(MAX_POLL_INTERVAL, poll_interval + 0.1)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            console.print("\n")
            self.log("Exiting...")

        except Exception as e:
            self.set_state("error")
            self.log(f"Fatal error: {e}")
            import traceback

            traceback.print_exc()
