"""Hardware protocol regression tests; no connected devices or network required."""

from collections import deque
from contextlib import contextmanager
import json
from threading import Event, Lock, enumerate as enumerate_threads
from time import sleep as real_sleep
from unittest.mock import Mock

import pytest

from openshock_autoflasher import hardware_tests as hw


class Clock:
    now = 0.0
    reader_drained = None

    def monotonic(self):
        # Do not expire a virtual deadline while the real reader is still processing
        # already supplied bytes. sleep(0) does not guarantee it gets scheduled.
        if self.reader_drained is not None:
            assert self.reader_drained.wait(5), "RF reader did not drain the fake serial input"
        self.now += 0.01
        return self.now

    def sleep(self, seconds):
        self.now += seconds


class FakeSerial:
    def __init__(self, respond):
        self.respond = respond
        self.data = deque()
        self.writes = []
        self.closed = False
        self.lock = Lock()
        self.drained = Event()
        self.drained.set()

    def feed(self, text):
        with self.lock:
            self.drained.clear()
            self.data.extend(bytes([byte]) for byte in text.encode())

    def open(self):
        self.closed = False

    def close(self):
        self.closed = True

    def reset_input_buffer(self):
        with self.lock:
            self.data.clear()
            self.drained.set()

    def write(self, data):
        self.writes.append(data)
        self.respond(self, data.decode().strip())
        return len(data)

    def read(self, _size):
        with self.lock:
            if self.data:
                return self.data.popleft()
            # The previous byte has been parsed and any completed line enqueued
            # before the reader asks for another byte.
            self.drained.set()
        # Real serial reads block until input arrives or their timeout expires.
        real_sleep(0.0001)
        return b""


@pytest.fixture
def rig(monkeypatch):
    clock = Clock()
    monkeypatch.setattr(hw.time, "monotonic", clock.monotonic)
    monkeypatch.setattr(hw.time, "sleep", clock.sleep)
    rng = Mock()
    rng.sample.return_value = [12345, 40001, 60002]
    monkeypatch.setattr(hw.secrets, "SystemRandom", lambda: rng)
    state = {"rf": True, "ap": True}
    monitor = FakeSerial(lambda *_: None)
    monitor_lines = hw._monitor_lines

    @contextmanager
    def synchronized_monitor_lines(session):
        with monitor_lines(session) as lines:
            clock.reader_drained = monitor.drained
            try:
                yield lines
            finally:
                clock.reader_drained = None

    monkeypatch.setattr(hw, "_monitor_lines", synchronized_monitor_lines)
    monkeypatch.setattr(hw, "read_ap_ssid", lambda port: "OpenShock-AA:BB:CC:DD:EE:FF")
    monkeypatch.setattr(hw, "scan_ap", lambda *args, **kwargs: state["ap"])

    def respond(port, command):
        if command == "$sysinfo":
            port.feed("$SYS$|Response|WiFiInfo|Connected|false\r\n")
        elif command.startswith("$rftransmit "):
            port.feed("$SYS$|Success|Command sent\r\n")
            if state["rf"]:
                payload = json.loads(command.removeprefix("$rftransmit "))
                mode = {"sound": "Beep", "vibrate": "Vibrate", "stop": "Stop"}[payload["type"]]
                remote_id = payload["id"]
                monitor.feed(f"ID: 0x{remote_id:X} ({remote_id}) | Channel: 1 | Mode: {mode}\r\n")
        elif command == "$factoryreset":
            port.feed("Resetting to factory defaults...\r\nRestarting...\r\n")

    device = FakeSerial(respond)

    # Session sets .port before .open(); delegate to the appropriate fake then.
    def factory(**_kwargs):
        proxy = Mock()

        def open_port():
            target = monitor if proxy.port == "monitor" else device
            target.dtr = proxy.dtr
            target.open()
            for name in ("read", "write", "close", "reset_input_buffer"):
                setattr(proxy, name, getattr(target, name))

        proxy.open = open_port
        return proxy

    monkeypatch.setattr(hw.serial, "Serial", factory)
    return state, device, monitor


def config(**kwargs):
    return hw.HardwareTestConfig(timeout=10, **kwargs)


def test_both_tests_use_real_protocol_and_close(rig):
    state, device, monitor = rig
    logs = []
    result = hw.run_hardware_tests("dut", config(wifi=True, rf_port="monitor"), logs.append)
    assert result.passed
    assert [check.name for check in result.checks] == ["wifi", "rf"]
    assert device.closed and monitor.closed
    assert monitor.dtr is True
    assert device.dtr is False
    commands = [
        json.loads(data.decode().split(" ", 1)[1])
        for data in device.writes
        if data.startswith(b"$rftransmit")
    ]
    assert commands == [
        {"model": "caixianlin", "id": 12345, "type": "sound", "intensity": 0, "durationMs": 1000},
        {"model": "caixianlin", "id": 40001, "type": "vibrate", "intensity": 1, "durationMs": 1000},
        {"model": "caixianlin", "id": 60002, "type": "stop", "intensity": 0, "durationMs": 300},
    ]
    assert len({command["id"] for command in commands}) == 3
    assert b"$factoryreset\n" not in device.writes
    assert not any(data.startswith(b"$networks") for data in device.writes)
    assert any("PASS WIFI" in line and "OpenShock-AA:BB:CC:DD:EE:FF" in line for line in logs)
    assert any("PASS RF" in line for line in logs)


def test_report_events_include_identity_checks_and_each_rf_command(rig):
    events = []
    result = hw.run_hardware_tests(
        "dut",
        config(wifi=True, rf_port="monitor", factory_reset_after_test=True),
        lambda _: None,
        on_event=lambda kind, value: events.append((kind, value)),
    )
    assert result.passed
    assert ("mac", "AA:BB:CC:DD:EE:FF") in events
    cases = [value for kind, value in events if kind == "rf_command"]
    assert [case["remote_id"] for case in cases] == [12345, 40001, 60002]
    assert [case["mode"] for case in cases] == ["Beep", "Vibrate", "Stop"]
    assert all(case["status"] == "passed" for case in cases)
    assert [value.name for kind, value in events if kind == "check"] == [
        "wifi",
        "rf",
        "factory_reset",
    ]


def test_wifi_uses_exact_hub_identity(rig, monkeypatch):
    scan = Mock(return_value=True)
    monkeypatch.setattr(hw, "scan_ap", scan)
    result = hw.run_hardware_tests("dut", config(wifi=True), lambda _: None)
    assert result.passed
    assert scan.call_args.args[0] == "OpenShock-AA:BB:CC:DD:EE:FF"


def test_explicit_ssid_skips_bootloader_and_serial(rig, monkeypatch):
    read_mac = Mock(side_effect=AssertionError("Must not connect"))
    monkeypatch.setattr(hw, "read_ap_ssid", read_mac)
    ssid = "OpenShock-11:22:33:44:55:66"
    scan = Mock(return_value=True)
    monkeypatch.setattr(hw, "scan_ap", scan)
    result = hw.run_hardware_tests("dut", config(wifi=True, wifi_ssid=ssid), lambda _: None)
    assert result.passed
    assert scan.call_args.args[0] == ssid
    read_mac.assert_not_called()
    assert not rig[1].writes


def test_stale_rf_frames_cannot_pass_and_missing_rf_fails(rig):
    state, device, monitor = rig
    state["rf"] = False
    monitor.feed("ID: 0x3039 (12345) | Channel: 1 | Mode: Beep\n")
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), lambda _: None)
    assert not result.passed
    assert device.closed and monitor.closed


@pytest.mark.parametrize(
    "frame",
    [
        "ID: 0x3038 (12344) | Channel: 1 | Mode: Beep",
        "ID: 0x3039 (12345) | Channel: 2 | Mode: Beep",
        "ID: 0x3039 (12345) | Channel: 1 | Mode: Stop",
        "ID: 0x3039 (12345) | Channel: 1 | Mode: Shock",
        "ID: 0x3039 (12344) | Channel: 1 | Mode: Beep",
        "unrelated boot log",
    ],
)
def test_rf_rejects_wrong_or_malformed_frames(rig, frame):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit"):
            monitor.feed(frame + "\n")

    device.respond = altered
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), lambda _: None)
    assert not result.passed


def test_wifi_failure_still_runs_rf(rig):
    state, _, _ = rig
    state["ap"] = False
    result = hw.run_hardware_tests("dut", config(wifi=True, rf_port="monitor"), lambda _: None)
    assert [check.passed for check in result.checks] == [False, True]


def test_monitor_alias_is_rejected_before_opening(tmp_path):
    target = tmp_path / "ttyUSB0"
    target.touch()
    alias = tmp_path / "monitor"
    alias.symlink_to(target)
    assert hw.same_port(str(target), str(alias))
    with pytest.raises(hw.HardwareTestError, match="separate"):
        hw.run_hardware_tests(str(target), config(rf_port=str(alias)), lambda _: None)


@pytest.mark.parametrize("timeout", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout(timeout):
    with pytest.raises(ValueError):
        hw.HardwareTestConfig(timeout=timeout)


def test_session_handles_fragmented_lines_and_error_redaction(rig):
    _, device, _ = rig
    with hw.SerialSession("dut", 1) as session:
        device.feed("$SYS$|Error|password=super-secret\n")
        with pytest.raises(hw.HardwareTestError, match="rejected") as error:
            session.wait_for("success", hw.time.monotonic() + 10)
        assert "super-secret" not in str(error.value)
    assert device.closed


@pytest.mark.parametrize("failed_case", [0, 1, 2])
def test_every_rf_case_is_required_and_all_are_attempted(rig, failed_case):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond
    sent = []

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit"):
            payload = json.loads(command.split(" ", 1)[1])
            mode = {"sound": "Beep", "vibrate": "Vibrate", "stop": "Stop"}[payload["type"]]
            remote_id = payload["id"]
            # Wrong mode for exactly one case; all the other cases match.
            if len(sent) == failed_case:
                mode = "Light"
            monitor.feed(f"ID: 0x{remote_id:X} ({remote_id}) | Channel: 1 | Mode: {mode}\n")
            sent.append(payload)

    device.respond = altered
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    assert len(sent) == 3
    assert sum(line.startswith("PASS RF [") for line in logs) == 2
    assert sum(line.startswith("FAIL RF [") for line in logs) == 1


def test_rf_old_id_with_correct_mode_cannot_pass_later_case(rig):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit"):
            payload = json.loads(command.split(" ", 1)[1])
            mode = {"sound": "Beep", "vibrate": "Vibrate", "stop": "Stop"}[payload["type"]]
            monitor.feed(f"ID: 0x3039 (12345) | Channel: 1 | Mode: {mode}\n")

    device.respond = altered
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    assert sum(line.startswith("PASS RF [") for line in logs) == 1
    assert sum(line.startswith("FAIL RF [") for line in logs) == 2


@pytest.mark.parametrize("ap_passed", [True, False])
def test_factory_reset_runs_last_even_after_failed_test(rig, ap_passed):
    state, device, monitor = rig
    state["ap"] = ap_passed
    result = hw.run_hardware_tests(
        "dut", config(wifi=True, rf_port="monitor", factory_reset_after_test=True), lambda _: None
    )
    assert [check.name for check in result.checks] == ["wifi", "rf", "factory_reset"]
    assert [check.passed for check in result.checks] == [ap_passed, True, True]
    assert result.passed is ap_passed
    commands = [data for data in device.writes if data != b"$sysinfo\n"]
    assert len(commands) == 4
    assert commands[-1] == b"$factoryreset\n"
    assert device.writes[-1] == b"$sysinfo\n"  # Hub must respond after reset.
    assert device.closed and monitor.closed


@pytest.mark.parametrize(
    "reply",
    [
        "",
        "Resetting to factory defaults...\n",
        "Restarting...\n",
        "$SYS$|Error|Unknown command\n",
    ],
)
def test_factory_reset_requires_both_reset_messages(rig, reply):
    _, device, _ = rig
    respond = device.respond

    def altered(port, command):
        if command == "$factoryreset":
            port.feed(reply)
        else:
            respond(port, command)

    device.respond = altered
    result = hw.run_hardware_tests(
        "dut", config(wifi=True, factory_reset_after_test=True), lambda _: None
    )
    assert not result.passed
    assert result.checks[0].passed
    assert result.checks[-1].name == "factory_reset"
    assert not result.checks[-1].passed
    assert device.closed


def test_factory_reset_must_respond_after_reboot(rig):
    _, device, _ = rig
    respond = device.respond
    reset_sent = False

    def altered(port, command):
        nonlocal reset_sent
        if command == "$sysinfo" and reset_sent:
            return
        respond(port, command)
        if command == "$factoryreset":
            reset_sent = True

    device.respond = altered
    result = hw.run_hardware_tests(
        "dut", config(wifi=True, factory_reset_after_test=True), lambda _: None
    )
    assert not result.passed
    assert "ready" in result.checks[-1].detail
    assert device.closed


def test_factory_reset_failure_keeps_original_test_failure(rig):
    state, device, _ = rig
    state["ap"] = False
    respond = device.respond
    device.respond = lambda port, command: (
        None if command == "$factoryreset" else respond(port, command)
    )
    result = hw.run_hardware_tests(
        "dut", config(wifi=True, factory_reset_after_test=True), lambda _: None
    )
    assert [check.passed for check in result.checks] == [False, False]


def test_factory_reset_never_targets_monitor(rig):
    _, device, monitor = rig
    with pytest.raises(hw.HardwareTestError, match="separate"):
        hw.run_hardware_tests(
            "monitor", config(rf_port="monitor", factory_reset_after_test=True), lambda _: None
        )
    assert not device.writes and not monitor.writes


def test_factory_reset_requires_tests():
    with pytest.raises(ValueError, match="requires at least one"):
        config(factory_reset_after_test=True)


def test_auto_rf_without_selected_port_cannot_test_or_reset(rig):
    _, device, monitor = rig
    settings = config(rf_auto_detect=True, factory_reset_after_test=True)
    assert settings.enabled and settings.rf_enabled
    with pytest.raises(hw.HardwareTestError, match="Select the RF tester"):
        hw.run_hardware_tests("dut", settings, lambda _: None)
    assert not device.writes and not monitor.writes


def test_silent_tester_reports_progress_and_specific_failure(rig):
    state, _, _ = rig
    state["rf"] = False
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    assert "No serial data from tester monitor" in result.checks[0].detail
    assert any("Hub acknowledged RF command" in line for line in logs)
    assert any("Waiting for RF on monitor" in line for line in logs)


def test_missing_hub_ack_is_distinguished_from_silent_tester(rig):
    _, device, _ = rig
    respond = device.respond
    device.respond = lambda port, command: (
        None if command.startswith("$rftransmit") else respond(port, command)
    )
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    assert "Hub did not acknowledge RF transmit" in result.checks[0].detail
    assert not any("Hub acknowledged RF command" in line for line in logs)
    assert not any("Waiting for RF on" in line for line in logs)


def test_unrecognized_tester_output_is_distinguished_from_silence(rig):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit"):
            monitor.feed("boot text from a different sketch\n")

    device.respond = altered
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    assert "bytes but no valid monitor frames" in result.checks[0].detail
    assert "boot text from a different sketch" in result.checks[0].detail
    assert any(
        'Tester output (unrecognized): "boot text from a different sketch"' in line for line in logs
    )


def test_reported_monitor_format_is_recognized_as_an_unmatched_frame(rig):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit"):
            monitor.feed("ID: 0x2E16 (11798) | Channel: 1 | Mode: Shock\r\n")

    device.respond = altered
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    assert (
        "Received 1 unmatched frames; last was ID 11798, channel 1, Shock"
        in result.checks[0].detail
    )
    assert any("1 unmatched frames, 0 unrecognized lines" in line for line in logs)
    assert not any("Tester output (unrecognized)" in line for line in logs)


def test_unrecognized_output_is_escaped_and_limited(rig):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit"):
            monitor.feed(("\x1b[2J" + "garbled " * 100 + "\n") * 10)

    device.respond = altered
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    previews = [line for line in logs if line.startswith("Tester output (unrecognized):")]
    assert len(previews) == 15  # At most five samples for each of the three cases.
    assert all("\x1b" not in line and "\\u001b" in line for line in previews)
    assert all(len(line) < 300 for line in previews)


def test_unterminated_tester_data_is_visible_in_progress_and_failure(rig):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit"):
            monitor.feed("incomplete data " + "x" * 500 + "excluded-tail")

    device.respond = altered
    logs = []
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), logs.append)
    assert not result.passed
    assert "incomplete data" in result.checks[0].detail
    assert "excluded-tail" not in result.checks[0].detail
    assert any("Tester data without a complete line" in line for line in logs)


def test_boot_output_does_not_prevent_valid_rf_frames_from_passing(rig):
    _, device, monitor = rig
    respond = device.respond

    def altered(port, command):
        if command.startswith("$rftransmit"):
            monitor.feed("Shock ID Monitor Started\n")
        respond(port, command)

    device.respond = altered
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), lambda _: None)
    assert result.passed


def test_serial_preview_is_bounded_and_cleared_between_commands(rig):
    _, _, monitor = rig
    with hw.SerialSession("monitor", 1) as session:
        monitor.feed("a" * 300)
        for _ in range(300):
            session.line()
        assert bytes(session.received_preview) == b"a" * 256
        session.clear()
        monitor.feed("new\n")
        for _ in range(4):
            session.line()
        assert bytes(session.received_preview) == b"new\n"


def test_native_usb_tester_receives_only_with_dtr_asserted(rig):
    _, device, monitor = rig
    respond = device.respond

    def altered(port, command):
        respond(port, command)
        if command.startswith("$rftransmit") and not monitor.dtr:
            monitor.reset_input_buffer()

    device.respond = altered
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), lambda _: None)
    assert result.passed


def test_rf_is_consumed_before_hub_acknowledgement(rig):
    _, device, monitor = rig
    consumed = Event()
    read = monitor.read
    respond = device.respond

    def read_monitor(size):
        byte = read(size)
        if byte == b"\n":
            consumed.set()
        return byte

    def broadcast_before_ack(port, command):
        if not command.startswith("$rftransmit"):
            respond(port, command)
            return
        consumed.clear()
        payload = json.loads(command.removeprefix("$rftransmit "))
        mode = {"sound": "Beep", "vibrate": "Vibrate", "stop": "Stop"}[payload["type"]]
        remote_id = payload["id"]
        monitor.feed(f"ID: 0x{remote_id:X} ({remote_id}) | Channel: 1 | Mode: {mode}\n")
        # Do not acknowledge until the immediate broadcast has actually been read.
        assert consumed.wait(1), "Tester was not being read while hub acknowledgement was pending"
        port.feed("$SYS$|Success|Command sent\n")

    monitor.read = read_monitor
    device.respond = broadcast_before_ack
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), lambda _: None)
    assert result.passed, result.checks[0].detail
    assert not any(thread.name == "rf-monitor-reader" for thread in enumerate_threads())


def test_rf_clock_waits_for_delayed_reader(rig):
    _, _, monitor = rig
    read = monitor.read
    first_read = True

    def delayed_read(size):
        nonlocal first_read
        if first_read:
            first_read = False
            real_sleep(0.1)
        return read(size)

    monitor.read = delayed_read
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), lambda _: None)
    assert result.passed, result.checks[0].detail


@pytest.mark.parametrize("failure", ["ack", "receiver", "timeout"])
def test_async_reader_is_stopped_after_failure(rig, failure):
    state, device, monitor = rig
    state["rf"] = False
    respond = device.respond
    if failure == "ack":
        state["rf"] = True

        def without_ack(port, command):
            respond(port, command)
            if command.startswith("$rftransmit"):
                port.reset_input_buffer()

        device.respond = without_ack
    elif failure == "receiver":
        monitor.read = Mock(side_effect=hw.serial.SerialException("Disconnected"))
    result = hw.run_hardware_tests("dut", config(rf_port="monitor"), lambda _: None)
    assert not result.passed
    if failure == "ack":
        assert "Hub did not acknowledge RF transmit" in result.checks[0].detail
    if failure == "receiver":
        assert "RF tester read failed: SerialException" in result.checks[0].detail
    assert len([data for data in device.writes if data.startswith(b"$rftransmit")]) == 3
    assert device.closed and monitor.closed
    assert not any(thread.name == "rf-monitor-reader" for thread in enumerate_threads())


def test_async_reader_stops_even_when_its_queue_is_full(rig):
    _, _, monitor = rig
    with hw.SerialSession("monitor", 1) as session:
        with hw._monitor_lines(session) as lines:
            monitor.feed("unrelated frame\n" * 300)
            for _ in range(1000):
                if lines.full():
                    break
                real_sleep(0.001)
            assert lines.full()
        assert not any(thread.name == "rf-monitor-reader" for thread in enumerate_threads())
