"""
Core flashing logic for OpenShock Auto-Flasher
"""

import hashlib
import importlib.metadata
import tempfile
import textwrap
import time
from contextlib import contextmanager, nullcontext
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from typing import Any, Iterator, Optional, List, Set

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
    SUPPORTED_CHIPS,
    INITIAL_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    POLL_BACKOFF_THRESHOLD,
    DEVICE_INIT_DELAY,
)
from .styles import StateColors, console
from .report import SessionReport, capture_identity
from .wifi import read_ap_ssid
from .hardware_tests import (
    CheckResult,
    HardwareTestConfig,
    HardwareTestError,
    HardwareTestResult,
    run_hardware_tests,
    same_port,
)


def normalize_chip(chip: Optional[str]) -> str:
    """Normalize and validate an optional esptool chip value."""
    if chip is None:
        return "auto"

    normalized_chip = chip.lower()
    if normalized_chip != "auto" and normalized_chip not in SUPPORTED_CHIPS:
        supported = ", ".join(("auto", *SUPPORTED_CHIPS))
        raise ValueError(f"Unsupported chip '{chip}'. Supported chips: {supported}")
    return normalized_chip


class AutoFlasher:
    """Main auto-flashing controller for OpenShock devices"""

    def __init__(
        self,
        channel: str = "stable",
        board: Optional[str] = None,
        erase_flash: bool = False,
        auto_flash: bool = True,
        post_flash_commands: Optional[List[str]] = None,
        post_flash_delay: float = 0.0,
        alert: bool = False,
        version: Optional[str] = None,
        chip: Optional[str] = None,
        hardware_tests: Optional[HardwareTestConfig] = None,
        test_only: bool = False,
        session_report: Optional[SessionReport] = None,
    ) -> None:
        self.channel: str = channel
        self.board: Optional[str] = board
        self.erase_flash: bool = erase_flash
        self.test_only: bool = test_only
        self.auto_flash: bool = auto_flash and not test_only
        self.post_flash_commands: List[str] = post_flash_commands or []
        self.post_flash_delay: float = post_flash_delay
        self.alert: bool = alert
        self.version: Optional[str] = version
        self.chip: str = normalize_chip(chip)
        self.hardware_tests = hardware_tests or HardwareTestConfig()
        self.session_report = session_report
        self._record: Optional[dict[str, Any]] = None
        self.rf_monitor_identity: Optional[tuple[Optional[int], Optional[int], str]] = None
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

    @contextmanager
    def _report_device(
        self, port: str, mode: str, firmware: str | None = None, board: str | None = None
    ) -> Iterator[None]:
        if self.session_report is None or self._record is not None:
            yield
            return
        usb: dict[str, Any] = {}
        try:
            info = next(
                (p for p in serial.tools.list_ports.comports() if same_port(p.device, port)), None
            )
            if info is not None:
                usb = {
                    key: getattr(info, key, None)
                    for key in (
                        "serial_number",
                        "vid",
                        "pid",
                        "manufacturer",
                        "product",
                        "description",
                        "location",
                    )
                }
        except Exception:
            pass
        self._record = self.session_report.start_device(
            port,
            board=board or self.board,
            mode=mode,
            firmware=firmware,
            tests={
                "wifi": self.hardware_tests.wifi,
                "rf": self.hardware_tests.rf_enabled,
                "factory_reset": self.hardware_tests.factory_reset_after_test,
            },
            usb=usb,
        )
        self._record["rf_tester_port"] = self.hardware_tests.rf_port
        try:
            if mode == "test_only" and (
                not self.hardware_tests.wifi or self.hardware_tests.wifi_ssid
            ):
                try:
                    self._report_identity(read_ap_ssid(port).removeprefix("OpenShock-"))
                except Exception as exc:
                    self._record["warnings"].append(f"MAC read unavailable: {type(exc).__name__}")
            yield
        except BaseException as exc:
            status = "failed" if isinstance(exc, Exception) else "interrupted"
            self.session_report.finish_device(self._record, status, str(exc) or type(exc).__name__)
            raise
        else:
            self.session_report.finish_device(self._record, "passed")
        finally:
            self._record = None

    def _report_stage(self, name: str, status: str) -> None:
        if self._record is not None and self.session_report is not None:
            self._record["stages"][name] = status
            self.session_report.save()

    def _report_identity(self, mac: str) -> None:
        if self._record is not None and self.session_report is not None:
            self._record.update(mac_address=mac.upper(), mac_source="hub base MAC")
            self.session_report.save()

    def _report_event(self, kind: str, value: Any) -> None:
        if self._record is None or self.session_report is None:
            return
        if kind == "start":
            self._record["tests"][value]["status"] = "in_progress"
        elif kind == "check":
            self._record["tests"][value.name] = {
                "status": "passed" if value.passed else "failed",
                "detail": value.detail,
                "elapsed_seconds": value.elapsed_seconds,
            }
        elif kind == "rf_command":
            self._record["rf_commands"].append(value)
        elif kind == "mac":
            self._report_identity(value)
        elif kind == "ap":
            self._record["expected_ap"] = value
        self.session_report.save()

    def set_state(self, state: str) -> None:
        """Change state and update terminal background"""
        self.state = state
        self.current_style = self.get_style()

    def play_alert(self) -> None:
        """Play an audible beep alert"""
        # Beep 4 times with a small delay between each beep
        for _ in range(4):
            print("\a", end="", flush=True)
            time.sleep(0.15)

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
        """Fetch latest version for the selected channel (cached), or use specified version"""
        if self.version:
            self.log(f"Using specified version: {self.version}")
            return self.version
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

    def execute_post_flash_commands(self, port: str) -> bool:
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

            ser = serial.Serial(port, 115200, timeout=0.2)
            time.sleep(0.5)  # Allow connection to stabilize

            # Clear any buffered data
            ser.reset_input_buffer()
            ser.reset_output_buffer()

            cmd_total = len(self.post_flash_commands)
            for i, cmd in enumerate(self.post_flash_commands, 1):
                # Discard any leftover output from previous command
                ser.reset_input_buffer()

                self.log(f"[{i}/{cmd_total}] Sending: {cmd}")

                # Send command with newline
                ser.write((cmd + "\n").encode("utf-8"))
                ser.flush()

                # Read response lines: stop after 200ms of silence or 2s total.
                # Skip lines that are the command echo (shell prompts like "> cmd").
                response_lines = []
                deadline = time.monotonic() + 2.0
                raw = bytearray()
                while time.monotonic() < deadline:
                    byte = ser.read(1)
                    if not byte:
                        break
                    raw.extend(byte)

                decoded = raw.decode("utf-8", errors="ignore")
                # Normalize \r\n and bare \r to \n so splitlines doesn't
                # duplicate content on carriage-return-only line endings.
                decoded = decoded.replace("\r\n", "\n").replace("\r", "\n")
                seen: Set[str] = set()
                for line in decoded.splitlines():
                    # Strip all non-printable characters (including null bytes that
                    # .strip() won't remove), then trim whitespace.
                    line = "".join(c for c in line if c.isprintable()).strip()
                    if not line or line == cmd:
                        continue
                    # Filter lines that are entirely one repeated character (e.g. "xxxxx...")
                    if len(set(line)) == 1:
                        continue
                    if line.startswith(">"):
                        line = line[1:].strip()
                        if line.startswith(cmd):
                            line = line[len(cmd) :].strip()
                    if not line:
                        continue
                    # Deduplicate identical lines (device can echo same line many times)
                    if line in seen:
                        continue
                    seen.add(line)
                    response_lines.append(line)

                if response_lines:
                    self.log(f"Response: {' '.join(response_lines)}")

                if i < cmd_total and self.post_flash_delay > 0:
                    delay_seconds = self.post_flash_delay / 1000
                    self.log(
                        "Waiting " f"{self.post_flash_delay:g}ms before next post-flash command..."
                    )
                    time.sleep(delay_seconds)

            ser.close()
            self.log("✓ Post-flash commands completed")
            self.log("=" * 60)

            return True

        except Exception as e:
            self.log(f"⚠ Warning: Post-flash command execution failed: {e}")
            self.log("Continuing anyway...")
            return False

    def _run_esptool(self, args: List[str], operation: str, retries: int = 1) -> None:
        """Run esptool with a small retry window for transient disconnects."""
        attempt_args = args.copy()
        for attempt in range(retries + 1):
            try:
                capture = (
                    capture_identity(self._record) if self._record is not None else nullcontext()
                )
                with capture:
                    esptool.main(attempt_args)
                return
            except StopIteration as e:
                # Some esptool/serial combinations can briefly drop transport
                # while the chip resets between phases.
                if attempt < retries:
                    self.log(
                        f"⚠ {operation} transport dropped, retrying "
                        f"({attempt + 1}/{retries})..."
                    )
                    time.sleep(1)
                    continue
                raise Exception(f"{operation} failed after retry: {e}") from e
            except esptool.util.FatalError as e:
                if str(e).startswith("Failed to start stub flasher"):
                    if attempt < retries:
                        # Stub startup precedes esptool's normal baud change.
                        # Go below its 115200 initial rate to slow that stage too.
                        baud_index = (
                            attempt_args.index("--baud") + 1 if "--baud" in attempt_args else None
                        )
                        current_baud = int(attempt_args[baud_index]) if baud_index else 115200
                        baud = min(current_baud, 57600 if current_baud > 57600 else 9600)
                        attempt_args = attempt_args.copy()
                        if baud_index is None:
                            attempt_args = ["--baud", str(baud), *attempt_args]
                        else:
                            attempt_args[baud_index] = str(baud)
                        self.log(
                            f"⚠ {operation} stub startup failed; reconnecting at {baud} baud "
                            f"({attempt + 1}/{retries})..."
                        )
                        if self._record is not None:
                            self._record["retries"].append(
                                {
                                    "operation": operation,
                                    "baud": baud,
                                    "reason": "stub startup failed",
                                }
                            )
                        time.sleep(1)
                        continue
                    raise Exception(
                        f"{operation} failed: {e}\n"
                        "Close other serial tools, power-cycle the hub, and check its USB cable and power."
                    ) from e
                # Port lock errors (EAGAIN 11) during reset; wait and retry.
                if attempt < retries and "Resource temporarily unavailable" in str(e):
                    self.log(
                        f"⚠ {operation} port busy (resetting device), retrying "
                        f"({attempt + 1}/{retries})..."
                    )
                    time.sleep(2)  # Longer delay for device reset
                    continue
                raise Exception(f"{operation} failed: {e}") from e
            except SystemExit as e:
                if e.code == 0:
                    return
                raise Exception(f"{operation} failed: {e}") from e

    def is_monitor_port(self, port: str) -> bool:
        return bool(self.hardware_tests.rf_port and same_port(port, self.hardware_tests.rf_port))

    def test_device(self, port: str) -> None:
        """Run enabled checks and show their results in the terminal."""
        if self.hardware_tests.rf_auto_detect and self.hardware_tests.rf_port is None:
            self.set_state("error")
            raise HardwareTestError("Select the RF tester port before testing")
        if self.is_monitor_port(port):
            self.set_state("error")
            raise HardwareTestError("Refusing to test the RF monitor port as a hub")
        with self._report_device(port, "test_only"):
            self._test_device(port)

    def _test_device(self, port: str) -> None:
        self.set_state("flashing")
        if self.test_only:
            self.log("=" * 60)
            self.log(f"Starting hardware tests for {self.board}")
            self.log(f"Port: {port}")
            self.log("=" * 60)
        try:
            result = run_hardware_tests(
                port, self.hardware_tests, self.log, on_event=self._report_event
            )
        except Exception as exc:
            detail = str(exc) if isinstance(exc, HardwareTestError) else type(exc).__name__
            result = HardwareTestResult(port, [CheckResult("setup", False, detail, 0)])
        for check in result.checks:
            self._report_event("check", check)
        try:
            if not result.passed:
                raise HardwareTestError(
                    "Hardware testing failed: "
                    + "; ".join(
                        f"{check.name}: {check.detail}"
                        for check in result.checks
                        if not check.passed
                    )
                )
        except Exception:
            self.set_state("error")
            raise
        self.set_state("done")
        if self.test_only:
            self.log("=" * 60)
        self.log("✓ All hardware tests passed")
        if self.test_only:
            self.log("=" * 60)
        if self.test_only and self.alert:
            self.play_alert()

    def flash_device(self, port: str, version: str, board: str) -> None:
        """Flash firmware to device"""
        if self.is_monitor_port(port):
            self.set_state("error")
            raise HardwareTestError("Refusing to flash the RF monitor port")
        with self._report_device(port, "flash", version, board):
            self._flash_device(port, version, board)

    def _flash_device(self, port: str, version: str, board: str) -> None:
        temp_firmware: Optional[Path] = None
        try:
            if self.hardware_tests.rf_auto_detect and self.hardware_tests.rf_port is None:
                raise HardwareTestError("Select the RF tester port before flashing")
            if self.is_monitor_port(port):
                raise HardwareTestError("Refusing to flash the RF monitor port")
            self.set_state("flashing")
            self.log("=" * 60)
            self.log(f"Starting flash process for {board}")
            self.log(f"Port: {port}")
            self.log(f"Version: {version}")
            self.log(f"Chip: {self.chip}")
            self.log("=" * 60)

            # Download firmware
            self._report_stage("download", "in_progress")
            firmware_data = self.download_firmware(version, board)
            if self._record is not None:
                self._record.update(
                    firmware_sha256=hashlib.sha256(firmware_data).hexdigest(),
                    firmware_size_bytes=len(firmware_data),
                )
            self._report_stage("download", "passed")

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
            base_args = [
                "--chip",
                self.chip,
                "--port",
                port,
                "--baud",
                BAUD_RATE,
            ]
            args = [
                *base_args,
                "write-flash",
            ]

            if self.erase_flash:
                self.log("Erasing flash...")
                self._report_stage("erase", "in_progress")
                erase_args = [
                    *base_args,
                    "erase-flash",
                ]

                self._run_esptool(erase_args, "Erase", retries=2)
                self._report_stage("erase", "passed")

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
            self._report_stage("flash", "in_progress")
            self._run_esptool(args, "Flash")
            self._report_stage("flash", "passed")

            # Execute post-flash commands if any
            if self.post_flash_commands:
                self._report_stage("post_flash", "in_progress")
                success = self.execute_post_flash_commands(port)
                self._report_stage("post_flash", "passed" if success else "failed")

            if self.hardware_tests.enabled:
                self.test_device(port)

            self.set_state("done")
            self.log("✓ Flashing complete!")
            self.log("=" * 60)
            self.log(
                "SUCCESS! Device flashed"
                + (" and hardware tests passed" if self.hardware_tests.enabled else " successfully")
            )
            self.log("=" * 60)

            # Play alert beep if enabled
            if self.alert:
                self.play_alert()

            # Cleanup
            temp_firmware.unlink(missing_ok=True)

        except Exception as e:
            self.set_state("error")
            if temp_firmware:
                temp_firmware.unlink(missing_ok=True)
            self.log(f"✗ Error during flashing: {e}")
            raise
        finally:
            if temp_firmware:
                temp_firmware.unlink(missing_ok=True)

    def prepare_rf_monitor(self, target_port: Optional[str] = None) -> None:
        """Reserve the first tester connection before accepting hubs to flash."""
        if not self.hardware_tests.rf_auto_detect or self.hardware_tests.rf_port is not None:
            return

        self.log("RF tester auto-detection: plug in the tester first, then the hubs.")
        previous: Optional[Set[str]] = None
        while True:
            ports = list(serial.tools.list_ports.comports())
            eligible = [
                p for p in ports if target_port is None or not same_port(p.device, target_port)
            ]
            current = {p.device for p in eligible}
            candidates = current if previous is None else current - previous
            if len(candidates) == 1:
                selected = next(p for p in eligible if p.device in candidates)
                self.hardware_tests = replace(self.hardware_tests, rf_port=selected.device)
                if isinstance(selected.serial_number, str) and selected.serial_number:
                    self.rf_monitor_identity = (selected.vid, selected.pid, selected.serial_number)
                self.known_ports = {p.device for p in ports}
                self.log(f"RF tester detected on {selected.device}; reserved for testing.")
                return
            if len(candidates) > 1:
                self.log("Multiple serial ports detected. Unplug and reconnect only the RF tester.")
            elif previous is None:
                self.log("Waiting for the RF tester to be plugged in...")
            previous = current
            time.sleep(INITIAL_POLL_INTERVAL)

    def refresh_rf_monitor_port(self, ports: list) -> None:
        """Follow the selected USB tester if its serial port number changes."""
        if self.rf_monitor_identity is None:
            return
        matches = [p for p in ports if (p.vid, p.pid, p.serial_number) == self.rf_monitor_identity]
        if len(matches) == 1 and matches[0].device != self.hardware_tests.rf_port:
            self.hardware_tests = replace(self.hardware_tests, rf_port=matches[0].device)
            self.log(f"RF tester reconnected on {matches[0].device}; reserved for testing.")

    def detect_new_port(self) -> Optional[List[str]]:
        """Detect when a new serial port is connected"""
        try:
            ports = list(serial.tools.list_ports.comports())
            self.refresh_rf_monitor_port(ports)
            current_ports = {p.device for p in ports}
            new_ports = current_ports - self.known_ports

            if new_ports:
                self.known_ports = current_ports
                # Return all new ports, not just the first
                targets = [
                    p.device
                    for p in ports
                    if p.device in new_ports
                    and not self.is_monitor_port(p.device)
                    and (
                        self.rf_monitor_identity is None
                        or (p.vid, p.pid, p.serial_number) != self.rf_monitor_identity
                    )
                ]
                return targets or None

            self.known_ports = current_ports
        except Exception as e:
            # Log port detection errors instead of silently ignoring
            self.log(f"⚠ Warning: Port detection error: {e}")
        return None

    def log_test_settings(self) -> None:
        """Show which hardware tests and cleanup steps are enabled."""
        self.log(f"WiFi AP test: {self.hardware_tests.wifi}")
        self.log(f"RF test: {self.hardware_tests.rf_enabled}")
        if self.hardware_tests.rf_port is not None:
            self.log(f"RF monitor port: {self.hardware_tests.rf_port}")
        elif self.hardware_tests.rf_auto_detect:
            self.log("RF monitor port: auto-detect (plug tester in first)")
        self.log(f"Factory reset after testing: {self.hardware_tests.factory_reset_after_test}")

    def run(self) -> None:
        """Main run loop"""
        self.set_state("waiting")

        # Print header with background
        _pkg_version = importlib.metadata.version("OpenShock-AutoFlasher")
        self.log(f"OpenShock Auto-Flasher {_pkg_version}")
        self.log("=" * 60)
        self.log(f"Channel: {self.channel}")
        self.log(f"Erase flash: {self.erase_flash}")
        self.log(f"Auto-flash: {self.auto_flash}")
        self.log(f"Test only: {self.test_only}")
        self.log_test_settings()
        self.log("=" * 60)
        self.log("")

        # Existing firmware can be tested without reaching the firmware service.
        version = None
        if not self.test_only:
            try:
                version = self.fetch_version()
                boards = self.fetch_boards(version)

                # Early validation: check board exists before waiting
                if self.board not in boards:
                    self.set_state("error")
                    self.log(f"Error: Board '{self.board}' not found " "in available boards")
                    self.log(f"Available boards: {', '.join(boards)}")
                    if self.session_report is not None:
                        self.session_report.finish("failed")
                    return

            except Exception as e:
                self.set_state("error")
                self.log(f"Error fetching firmware info: {e}")
                if self.session_report is not None:
                    self.session_report.finish("failed")
                return

        # Initialize known ports
        if self.hardware_tests.rf_auto_detect:
            self.prepare_rf_monitor()
        else:
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

                        if self.test_only or self.auto_flash:
                            # Give device time to initialize
                            time.sleep(DEVICE_INIT_DELAY)
                            try:
                                if self.test_only:
                                    self.test_device(new_port)
                                else:
                                    assert version is not None and self.board is not None
                                    self.flash_device(new_port, version, self.board)
                            except Exception as exc:
                                if self.test_only:
                                    self.set_state("error")
                                    self.log(f"Testing failed: {exc}")
                                self.log("Device failed. Connect the next device to continue.")

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
            if self.session_report is not None:
                self.session_report.finish_on_stop()
            console.print("\n")
            self.log("Exiting...")

        except Exception as e:
            self.set_state("error")
            self.log(f"Fatal error: {e}")
            if self.session_report is not None:
                self.session_report.finish("failed")
            import traceback

            traceback.print_exc()
