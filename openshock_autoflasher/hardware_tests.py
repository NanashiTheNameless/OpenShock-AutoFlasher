"""Post-flash hardware checks using OpenShock's automated serial protocol."""

from contextlib import contextmanager
from dataclasses import dataclass, field
import json
import math
import os
from queue import Empty, Full, Queue
import re
import secrets
from threading import Event, Thread
import time
from typing import Any, Callable, Iterator

import serial

from .wifi import AP_SSID, WiFiScanError, read_ap_ssid, scan_ap


@dataclass(frozen=True)
class HardwareTestConfig:
    wifi: bool = False
    wifi_ssid: str | None = None
    wifi_interface: str | None = None
    wifi_scan_command: tuple[str, ...] | None = None
    rf_port: str | None = None
    rf_auto_detect: bool = False
    timeout: float = 60.0
    factory_reset_after_test: bool = False

    def __post_init__(self) -> None:
        if self.factory_reset_after_test and not self.enabled:
            raise ValueError("Factory reset after testing requires at least one WiFi or RF test")
        if not math.isfinite(self.timeout) or self.timeout <= 0:
            raise ValueError("Test timeout must be finite and greater than zero")
        if self.wifi_ssid is not None and AP_SSID.fullmatch(self.wifi_ssid) is None:
            raise ValueError("Expected AP SSID must be OpenShock-XX:XX:XX:XX:XX:XX")
        if self.wifi_scan_command is not None and (
            not self.wifi_scan_command
            or any(not isinstance(arg, str) or not arg for arg in self.wifi_scan_command)
        ):
            raise ValueError("WiFi scan command must be a nonempty array of nonempty strings")

    @property
    def enabled(self) -> bool:
        return self.wifi or self.rf_enabled

    @property
    def rf_enabled(self) -> bool:
        return self.rf_auto_detect or self.rf_port is not None


def same_port(first: str, second: str) -> bool:
    """Resolve /dev/serial/by-id aliases as well as native port names."""
    return os.path.normcase(os.path.realpath(first)) == os.path.normcase(os.path.realpath(second))


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str
    elapsed_seconds: float


@dataclass
class HardwareTestResult:
    port: str
    checks: list[CheckResult] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.checks) and all(check.passed for check in self.checks)


class HardwareTestError(RuntimeError):
    """A hardware check failed or its result could not be verified."""


class SerialSession:
    """Bounded serial I/O, preserving fragmented lines and suppressing command echo."""

    def __init__(self, port: str, timeout: float, *, dtr: bool = False):
        self.port = port
        self.timeout = timeout
        self.dtr = dtr
        self.serial: serial.Serial | None = None
        self.pending = bytearray()
        self.received_bytes = 0
        self.received_preview = bytearray()

    def __enter__(self):
        deadline = time.monotonic() + self.timeout
        while True:
            connection = serial.Serial(port=None, baudrate=115200, timeout=0.1, write_timeout=2)
            # Hubs avoid reset; USB CDC testers need DTR asserted to send data.
            connection.dtr = self.dtr
            connection.rts = False
            connection.port = self.port
            try:
                connection.open()
                self.serial = connection
                return self
            except (serial.SerialException, OSError):
                connection.close()
                if time.monotonic() >= deadline:
                    raise HardwareTestError(f"Cannot open serial port {self.port}") from None
                time.sleep(0.2)

    def __exit__(self, *args):
        if self.serial is not None:
            self.serial.close()

    def clear(self) -> None:
        assert self.serial is not None
        self.pending.clear()
        self.received_bytes = 0
        self.received_preview.clear()
        self.serial.reset_input_buffer()

    def send(self, command: str) -> None:
        assert self.serial is not None
        payload = ("$" + command + "\n").encode("utf-8")
        if self.serial.write(payload) != len(payload):
            raise HardwareTestError("Incomplete serial command write")

    def line(self) -> str | None:
        assert self.serial is not None
        byte = self.serial.read(1)
        self.received_bytes += len(byte)
        if len(self.received_preview) < 256:
            self.received_preview.extend(byte)
        if byte in (b"\n", b"\r"):
            line = self.pending.decode("utf-8", errors="replace")
            self.pending.clear()
            return line
        self.pending.extend(byte)
        if len(self.pending) > 16384:
            raise HardwareTestError("Serial response exceeded maximum line length")
        return None

    def wait_for(self, prefix: str, deadline: float) -> str:
        while time.monotonic() < deadline:
            line = self.line()
            if line is None:
                continue
            if line.startswith("$SYS$|Error|"):
                # Firmware errors may contain command text, including WiFi passwords.
                raise HardwareTestError("Firmware rejected the serial command")
            if line.startswith(prefix):
                return line[len(prefix) :]
        raise HardwareTestError("Timed out waiting for firmware response")

    def command(self, command: str, prefix: str, *, timeout: float | None = None) -> str:
        self.clear()
        self.send(command)
        return self.wait_for(
            prefix, time.monotonic() + (self.timeout if timeout is None else timeout)
        )

    def ready(self) -> None:
        """Probe until the booting device answers, without relying on boot log wording."""
        deadline = time.monotonic() + self.timeout
        while time.monotonic() < deadline:
            self.clear()
            self.send("sysinfo")
            try:
                self.wait_for(
                    "$SYS$|Response|WiFiInfo|Connected|", min(deadline, time.monotonic() + 1)
                )
                return
            except HardwareTestError as exc:
                if not str(exc).startswith("Timed out"):
                    raise
        raise HardwareTestError("Device did not become ready before the timeout")


def check_wifi(
    port: str,
    config: HardwareTestConfig,
    log: Callable[[str], None],
    on_event: Callable[[str, Any], None] = lambda *_: None,
) -> str:
    ssid = config.wifi_ssid or read_ap_ssid(port)
    if config.wifi_ssid is None:
        on_event("mac", ssid.removeprefix("OpenShock-"))
    on_event("ap", ssid)
    log(f"Looking for AP {ssid}...")
    deadline = time.monotonic() + config.timeout
    while time.monotonic() < deadline:
        if scan_ap(
            ssid, deadline, interface=config.wifi_interface, command=config.wifi_scan_command
        ):
            return f"Hub broadcasts {ssid}"
        time.sleep(min(1.0, max(0, deadline - time.monotonic())))
    raise HardwareTestError(f"Hub AP {ssid} was not observed in a fresh WiFi scan")


RF_MESSAGE = re.compile(
    r"^ID: 0x([0-9a-fA-F]{1,4}) \((\d{1,5})\) \| Channel: ([1-3]) \| Mode: (Shock|Vibrate|Beep|Light|Stop)$"
)


# The monitor reports Stop for a zero-power vibration frame.
RF_CASES = (
    ("sound", "Beep", 0, 1000),
    ("vibrate", "Vibrate", 1, 1000),
    ("stop", "Stop", 0, 300),
)


@contextmanager
def _monitor_lines(monitor: SerialSession) -> Iterator[Queue[str | Exception]]:
    """Capture tester output independently of the hub's command/acknowledgement."""
    monitor.clear()
    lines: Queue[str | Exception] = Queue(maxsize=256)
    stop = Event()
    started = Event()

    def enqueue(item: str | Exception) -> None:
        while not stop.is_set():
            try:
                lines.put(item, timeout=0.1)
                return
            except Full:
                continue

    def read() -> None:
        started.set()
        try:
            while not stop.is_set():
                line = monitor.line()
                if line:
                    enqueue(line)
        except Exception as exc:
            enqueue(exc)

    reader = Thread(target=read, name="rf-monitor-reader")
    reader.start()
    try:
        started.wait()
        yield lines
    finally:
        stop.set()
        # Serial reads and queue writes both have short timeouts. Join before
        # closing or clearing the port so cases never have competing readers.
        reader.join()


def check_rf_command(
    device: SerialSession,
    monitor: SerialSession,
    config: HardwareTestConfig,
    remote_id: int,
    command_type: str,
    mode: str,
    intensity: int,
    duration_ms: int,
    log: Callable[[str], None],
) -> None:
    command = "rftransmit " + json.dumps(
        {
            "model": "caixianlin",
            "id": remote_id,
            "type": command_type,
            "intensity": intensity,
            "durationMs": duration_ms,
        },
        separators=(",", ":"),
    )
    with _monitor_lines(monitor) as lines:
        log(f"Listening on tester {monitor.port}; waiting for hub to acknowledge RF command...")
        try:
            device.command(command, "$SYS$|Success|Command sent", timeout=min(5.0, config.timeout))
        except HardwareTestError as exc:
            raise HardwareTestError(f"Hub did not acknowledge RF transmit: {exc}") from exc
        log(
            f"Hub acknowledged RF command; waiting on tester {monitor.port} (up to {config.timeout:g}s)..."
        )
        deadline = time.monotonic() + config.timeout
        next_update = time.monotonic() + 5
        frames = 0
        unrecognized = 0
        last_frame = ""
        while time.monotonic() < deadline:
            try:
                line = lines.get_nowait()
            except Empty:
                line = None
                time.sleep(0.01)
            if isinstance(line, Exception):
                raise HardwareTestError(f"RF tester read failed: {type(line).__name__}") from line
            match = RF_MESSAGE.fullmatch(line) if line else None
            if (
                match
                and int(match[1], 16) == int(match[2]) == remote_id
                and match[3] == "1"
                and match[4] == mode
            ):
                return
            if match:
                frames += 1
                last_frame = f"ID {match[2]}, channel {match[3]}, {match[4]}"
                if frames <= 3:
                    log(f"Tester received {last_frame}; does not match this test.")
            elif line:
                unrecognized += 1
                if unrecognized <= 5:
                    # Escape control characters so boot logs or garbled serial data
                    # cannot overwrite the terminal. Keep noisy output bounded.
                    preview = json.dumps(line[:240], ensure_ascii=True)
                    log(f"Tester output (unrecognized): {preview}")
            now = time.monotonic()
            if now >= next_update:
                log(
                    f"Waiting for RF on {monitor.port}: {max(0, deadline - now):.0f}s left, "
                    f"{monitor.received_bytes} serial bytes, {frames} unmatched frames, "
                    f"{unrecognized} unrecognized lines"
                )
                if monitor.received_bytes and not frames and not unrecognized:
                    raw_preview = bytes(monitor.received_preview)
                    log(f"Tester data without a complete line (first 256 bytes): {raw_preview!r}")
                next_update = now + 5
        if monitor.received_bytes == 0:
            detail = f"No serial data from tester {monitor.port}; check tester port, receiver wiring and firmware"
        elif frames == 0:
            detail = f"Tester {monitor.port} sent {monitor.received_bytes} bytes but no valid monitor frames"
            detail += f". First 256 bytes: {bytes(monitor.received_preview)!r}"
        else:
            detail = f"Received {frames} unmatched frames; last was {last_frame}"
        raise HardwareTestError(
            f"No matching RF frame for ID {remote_id}, channel 1, {mode}. {detail}"
        )


def check_rf(
    device: SerialSession,
    monitor: SerialSession,
    config: HardwareTestConfig,
    log: Callable[[str], None],
    on_event: Callable[[str, Any], None] = lambda *_: None,
) -> str:
    # Sampling without replacement prevents any case from accepting an earlier ID.
    ids = secrets.SystemRandom().sample(range(1, 65536), len(RF_CASES))
    failures = []
    for index, (remote_id, case) in enumerate(zip(ids, RF_CASES), 1):
        command_type, mode, intensity, duration_ms = case
        label = f"RF [{index}/{len(RF_CASES)}] ID {remote_id}, channel 1, {mode}"
        log(f"Testing {label}...")
        start = time.monotonic()
        status, detail = "interrupted", "Command interrupted"
        try:
            check_rf_command(
                device, monitor, config, remote_id, command_type, mode, intensity, duration_ms, log
            )
            log(f"PASS {label}")
            status, detail = "passed", "ID, channel and mode matched"
        except Exception as exc:
            status = "failed"
            detail = str(exc) if isinstance(exc, HardwareTestError) else type(exc).__name__
            failures.append(f"{label}: {detail}")
            log(f"FAIL {label}: {detail}")
        finally:
            on_event(
                "rf_command",
                {
                    "remote_id": remote_id,
                    "channel": 1,
                    "mode": mode,
                    "intensity": intensity,
                    "duration_ms": duration_ms,
                    "status": status,
                    "detail": detail,
                    "elapsed_seconds": round(time.monotonic() - start, 3),
                },
            )
            # Wait out the RF burst and monitor's 200ms debounce before the next case.
            time.sleep(max(0, start + duration_ms / 1000 + 0.3 - time.monotonic()))
    if failures:
        raise HardwareTestError("; ".join(failures))
    return f"All {len(RF_CASES)} CaiXianlin commands matched distinct IDs, channel 1 and mode"


def factory_reset_hub(port: str, config: HardwareTestConfig) -> str:
    with SerialSession(port, config.timeout) as device:
        device.ready()
        device.clear()
        device.send("factoryreset")
        # This handler prints plain text rather than a $SYS$ success response.
        deadline = time.monotonic() + config.timeout
        device.wait_for("Resetting to factory defaults...", deadline)
        device.wait_for("Restarting...", deadline)
    time.sleep(2)
    with SerialSession(port, config.timeout) as device:
        device.ready()
    return "Factory reset acknowledged; hub responded after restart"


def run_hardware_tests(
    port: str,
    config: HardwareTestConfig,
    log: Callable[[str], None],
    *,
    on_event: Callable[[str, Any], None] = lambda *_: None,
) -> HardwareTestResult:
    if config.rf_auto_detect and config.rf_port is None:
        raise HardwareTestError("Select the RF tester port before testing")
    if config.rf_port and same_port(port, config.rf_port):
        raise HardwareTestError("The RF monitor and device under test must use separate ports")
    result = HardwareTestResult(port)
    if not config.enabled:
        return result
    for name in ("wifi", "rf", "factory_reset"):
        if (
            (name == "wifi" and not config.wifi)
            or (name == "rf" and config.rf_port is None)
            or (name == "factory_reset" and not config.factory_reset_after_test)
        ):
            continue
        start = time.monotonic()
        on_event("start", name)
        log(f"Testing {name.upper()}...")
        try:
            if name == "wifi":
                detail = check_wifi(port, config, log, on_event)
            elif name == "factory_reset":
                detail = factory_reset_hub(port, config)
            else:
                assert config.rf_port is not None
                with SerialSession(port, config.timeout) as device:
                    device.ready()
                    with SerialSession(config.rf_port, config.timeout, dtr=True) as monitor:
                        # Some monitor boards reset when their serial connection opens.
                        time.sleep(2)
                        detail = check_rf(device, monitor, config, log, on_event)
            passed = True
        except Exception as exc:
            passed = False
            detail = (
                str(exc)
                if isinstance(exc, (HardwareTestError, WiFiScanError))
                else f"{type(exc).__name__} during hardware test"
            )
        check = CheckResult(name, passed, detail, round(time.monotonic() - start, 3))
        result.checks.append(check)
        on_event("check", check)
        log(f"{'PASS' if passed else 'FAIL'} {name.upper()}: {detail}")
    return result
