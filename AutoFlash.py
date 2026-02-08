#!/usr/bin/env python3
"""
OpenShock Auto-Flasher
Automatically flashes OpenShock hubs when plugged in
Background colors indicate status: Blue=Waiting, Yellow=Flashing, Green=Done, Red=Error
"""

import argparse
import hashlib
import os
import signal
import sys
import textwrap
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import esptool
import requests
import serial.tools.list_ports
from rich.console import Console
from rich.style import Style


# Color styles for different states
class StateColors:
    WAITING = Style(bgcolor="blue", color="white", bold=True)
    FLASHING = Style(bgcolor="yellow", color="black", bold=True)
    DONE = Style(bgcolor="green", color="black", bold=True)
    ERROR = Style(bgcolor="red", color="white", bold=True)


console = Console(force_terminal=True, color_system="truecolor")


class AutoFlasher:
    def __init__(
        self, channel="stable", board=None, erase_flash=False, auto_flash=True
    ):
        self.channel = channel
        self.board = board
        self.erase_flash = erase_flash
        self.auto_flash = auto_flash
        self.base_url = "https://firmware.openshock.org"
        self.known_ports = set()
        self.state = "waiting"
        self.current_style = StateColors.WAITING
        self.version_cache = None  # Cache version to avoid refetching
        self.boards_cache = None  # Cache boards list

    def get_style(self):
        """Get style based on current state"""
        styles = {
            "waiting": StateColors.WAITING,
            "flashing": StateColors.FLASHING,
            "done": StateColors.DONE,
            "error": StateColors.ERROR,
        }
        return styles.get(self.state, StateColors.WAITING)

    def set_state(self, state):
        """Change state and update terminal background"""
        self.state = state
        self.current_style = self.get_style()

    def log(self, message):
        """Print log message with current background"""
        timestamp = time.strftime("%H:%M:%S")
        # Fill entire width with background color
        max_len = console.width - 2
        text = f"[{timestamp}] {message}"

        # Wrap text if it's too long
        if len(text) > max_len:
            # Wrap the text, preserving words
            wrapped_lines = textwrap.wrap(
                text, width=max_len, break_long_words=False, break_on_hyphens=False
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

    def fetch_version(self):
        """Fetch latest version for the selected channel (cached)"""
        if self.version_cache:
            return self.version_cache
        url = f"{self.base_url}/version-{self.channel}.txt"
        self.log(f"Fetching version from {self.channel} channel...")
        response = requests.get(url)
        response.raise_for_status()
        self.version_cache = response.text.strip()
        self.log(f"Latest {self.channel} version: {self.version_cache}")
        return self.version_cache

    def fetch_boards(self, version):
        """Fetch available boards for a version (cached)"""
        if self.boards_cache:
            return self.boards_cache
        url = f"{self.base_url}/{version}/boards.txt"
        self.log("Fetching available boards...")
        response = requests.get(url)
        response.raise_for_status()
        self.boards_cache = [line.strip() for line in response.text.strip().split("\n")]
        self.log(f"Available boards: {', '.join(self.boards_cache)}")
        return self.boards_cache

    def download_firmware(self, version, board):
        """Download and verify firmware binary with progress indicator"""
        self.log(f"Downloading firmware for {board}...")

        firmware_url = f"{self.base_url}/{version}/{board}/firmware.bin"
        hash_url = f"{self.base_url}/{version}/{board}/hashes.sha256.txt"

        # Parallel download of firmware and hash
        def download_firmware_data():
            response = requests.get(firmware_url, stream=True)
            response.raise_for_status()
            return response.content

        def download_hash_data():
            response = requests.get(hash_url)
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

        # Verify hash
        calculated_hash = hashlib.sha256(firmware_data).hexdigest()
        if calculated_hash != expected_hash:
            raise ValueError(
                f"Hash mismatch! Expected {expected_hash}, got {calculated_hash}"
            )

        self.log(f"✓ Firmware downloaded and verified ({len(firmware_data)} bytes)")
        return firmware_data

    def flash_device(self, port, version, board):
        """Flash firmware to device"""
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
            temp_firmware = Path("/tmp/openshock_firmware.bin")
            temp_firmware.write_bytes(firmware_data)

            # Prepare esptool arguments
            args = [
                "--port",
                port,
                "--baud",
                "460800",
                "--chip",
                "auto",
                "write-flash",
            ]

            if self.erase_flash:
                self.log("Erasing flash...")
                erase_args = ["--port", port, "--baud", "460800", "erase-flash"]

                try:
                    esptool.main(erase_args)
                except SystemExit as e:
                    if e.code != 0:
                        raise Exception(f"Erase failed with exit code {e.code}")

                self.log("✓ Erase complete")

            args.extend(
                [
                    "--flash-mode",
                    "dio",
                    "--flash-freq",
                    "80m",
                    "--flash-size",
                    "detect",
                    "0x0000",
                    str(temp_firmware),
                ]
            )

            self.log("Flashing firmware...")

            try:
                esptool.main(args)
            except SystemExit as e:
                if e.code != 0:
                    raise Exception(f"Flash failed with exit code {e.code}")

            self.log("Verifying flash...")
            verify_args = [
                "--port",
                port,
                "--baud",
                "460800",
                "--chip",
                "auto",
                "verify-flash",
                "0x0000",
                str(temp_firmware),
            ]

            try:
                esptool.main(verify_args)
            except SystemExit as e:
                if e.code != 0:
                    raise Exception(f"Verification failed with exit code {e.code}")

            self.set_state("done")
            self.log("✓ Verification complete!")
            self.log("✓ Flashing complete!")
            self.log("=" * 60)
            self.log("SUCCESS! Device flashed successfully")
            self.log("=" * 60)

            # Cleanup
            temp_firmware.unlink(missing_ok=True)

        except Exception as e:
            self.set_state("error")
            self.log(f"✗ Error during flashing: {e}")
            raise

    def detect_new_port(self):
        """Detect when a new serial port is connected (with smarter polling)"""
        try:
            current_ports = set([p.device for p in serial.tools.list_ports.comports()])
            new_ports = current_ports - self.known_ports

            if new_ports:
                self.known_ports = current_ports
                return list(new_ports)[0]

            self.known_ports = current_ports
        except Exception:
            pass  # Silently ignore errors in port detection
        return None

    def run(self):
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

            # Early validation: check if board exists before waiting for devices
            if self.board not in boards:
                self.set_state("error")
                self.log(f"Error: Board '{self.board}' not found in available boards")
                self.log(f"Available boards: {', '.join(boards)}")
                return

            self.log(f"✓ Board '{self.board}' validated successfully")

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
            poll_interval = 0.5
            consecutive_checks = 0

            while True:
                new_port = self.detect_new_port()

                if new_port:
                    self.log(f"✓ Device detected on {new_port}")
                    poll_interval = 0.5  # Reset to fast polling after device detected
                    consecutive_checks = 0

                    if self.auto_flash:
                        time.sleep(1)  # Give device time to initialize
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
                    if consecutive_checks > 10:
                        poll_interval = min(1.0, poll_interval + 0.1)

                time.sleep(poll_interval)

        except KeyboardInterrupt:
            # Should not reach here due to signal handler, but just in case
            console.print("\n")
            self.log("Exiting...")

        except Exception as e:
            self.set_state("error")
            self.log(f"Fatal error: {e}")
            import traceback

            traceback.print_exc()


def main():
    # Set up signal handler for clean exit on Ctrl+C
    def signal_handler(sig, frame):
        console.print("\n")
        console.print("Exiting...", style=Style(color="white"))
        console.print("\033[0m")  # Reset terminal
        os._exit(0)  # Force immediate exit

    signal.signal(signal.SIGINT, signal_handler)

    parser = argparse.ArgumentParser(description="OpenShock Auto-Flasher")
    parser.add_argument(
        "--channel",
        "-c",
        choices=["stable", "beta", "develop"],
        default="stable",
        help="Firmware channel (default: stable)",
    )
    parser.add_argument("--board", "-b", required=True, help="Board type (required)")
    parser.add_argument(
        "--erase", "-e", action="store_true", help="Erase flash before flashing"
    )
    parser.add_argument(
        "--no-auto",
        "-n",
        action="store_true",
        help="Disable auto-flash (just detect devices)",
    )

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    flasher = AutoFlasher(
        channel=args.channel,
        board=args.board,
        erase_flash=args.erase,
        auto_flash=not args.no_auto,
    )

    flasher.run()

    # Reset terminal on exit
    console.print("\033[0m")


if __name__ == "__main__":
    main()
