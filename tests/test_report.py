"""Session reports preserve device attempts, failures, identity and test details."""

from io import StringIO
from types import SimpleNamespace
from unittest.mock import Mock, patch

import pytest

from openshock_autoflasher.flasher import AutoFlasher
from openshock_autoflasher.hardware_tests import (
    CheckResult,
    HardwareTestConfig,
    HardwareTestError,
    HardwareTestResult,
)
from openshock_autoflasher.report import IdentityOutput, SessionReport


def test_single_file_contains_all_attempts_and_escapes_device_text(tmp_path):
    report = SessionReport(str(tmp_path / "session.html"))
    for status in ("passed", "failed", "interrupted"):
        record = report.start_device(
            "hub",
            board="board",
            mode="flash",
            firmware="1.2.3",
            tests={"wifi": True, "rf": False},
            usb={"serial_number": "<script>USB</script>"},
        )
        record["mac_address"] = "AA:BB:CC:DD:EE:FF"
        report.finish_device(record, status, "<bad>" if status == "failed" else None)
    report.finish("interrupted")
    assert list(tmp_path.iterdir()) == [report.path]
    html = report.path.read_text()
    assert "3 attempts" in html and "AA:BB:CC:DD:EE:FF" in html
    assert "&lt;script&gt;USB&lt;/script&gt;" in html and "<script>" not in html
    assert [d["status"] for d in report.data["devices"]] == ["passed", "failed", "interrupted"]
    assert all(
        d["finished_at"] and d["elapsed_seconds"] is not None for d in report.data["devices"]
    )


def test_existing_report_is_not_overwritten(tmp_path):
    path = tmp_path / "session.html"
    path.write_text("keep")
    with pytest.raises(FileExistsError):
        SessionReport(str(path))
    assert path.read_text() == "keep"


@pytest.mark.parametrize("stop", ["signal", "keyboard", "error"])
@pytest.mark.parametrize("device_status", [None, "passed", "failed", "interrupted"])
def test_cli_stop_preserves_finished_attempts(tmp_path, monkeypatch, stop, device_status):
    from openshock_autoflasher.cli import main

    report = SessionReport(str(tmp_path / "session.html"))
    if device_status is not None:
        device = report.start_device(
            "hub", board="board", mode="flash", firmware="1", tests={}, usb={}
        )
        report.finish_device(device, device_status)
    monkeypatch.setattr("sys.argv", ["OPSH-AutoFlash", "--board", "board"])
    with (
        patch("openshock_autoflasher.cli.SessionReport", return_value=report),
        patch("openshock_autoflasher.cli.AutoFlasher") as flasher,
        patch("openshock_autoflasher.cli.signal.signal") as register_signal,
    ):

        def stop_run():
            if stop == "signal":
                register_signal.call_args.args[1](2, None)
            elif stop == "keyboard":
                raise KeyboardInterrupt()
            else:
                raise SystemExit(1)

        flasher.return_value.run.side_effect = stop_run
        with pytest.raises((SystemExit, KeyboardInterrupt)):
            main()
    expected = (
        "failed"
        if stop == "error"
        else "interrupted" if device_status == "interrupted" else "completed"
    )
    assert report.data["status"] == expected
    assert report.data["finished_at"] is not None
    assert f"class='status {expected}'" in report.path.read_text()
    if device_status is not None:
        assert report.data["devices"][0]["status"] == device_status


def test_flasher_keyboard_interrupt_while_waiting_completes_report(reporter):
    flasher, report = reporter
    flasher.test_only = True
    with patch.object(flasher, "detect_new_port", side_effect=KeyboardInterrupt()):
        flasher.run()
    assert report.data["status"] == "completed"
    assert report.data["finished_at"] is not None


def test_ctrl_c_during_esptool_does_not_count_flash_as_success(reporter, monkeypatch):
    from openshock_autoflasher.cli import main

    flasher, report = reporter
    monkeypatch.setattr("sys.argv", ["OPSH-AutoFlash", "--board", "board", "--port", "hub"])
    with (
        patch("openshock_autoflasher.cli.SessionReport", return_value=report),
        patch("openshock_autoflasher.cli.AutoFlasher", return_value=flasher),
        patch("openshock_autoflasher.cli.signal.signal") as register_signal,
        patch.object(flasher, "fetch_version", return_value="1"),
        patch.object(flasher, "fetch_boards", return_value=["board"]),
        patch("openshock_autoflasher.flasher.esptool.main") as esptool,
        patch("openshock_autoflasher.flasher.run_hardware_tests") as hardware_tests,
    ):
        esptool.side_effect = lambda *_: register_signal.call_args.args[1](2, None)
        with pytest.raises(SystemExit) as stopped:
            main()
    assert stopped.value.code == 0
    assert report.data["status"] == "interrupted"
    device = report.data["devices"][0]
    assert device["status"] == device["stages"]["flash"] == "interrupted"
    assert device["tests"]["rf"]["status"] == "not_run"
    hardware_tests.assert_not_called()


def test_failed_atomic_update_preserves_previous_report(tmp_path):
    report = SessionReport(str(tmp_path / "session.html"))
    original = report.path.read_bytes()
    with patch("openshock_autoflasher.report.os.replace", side_effect=OSError("disk full")):
        with pytest.raises(OSError):
            report.save()
    assert report.path.read_bytes() == original
    assert list(tmp_path.iterdir()) == [report.path]


def test_identity_capture_handles_fragmented_output_without_hiding_it():
    output = StringIO()
    record = {}
    tee = IdentityOutput(output, record)
    tee.write("Chip type:          ESP32-D0WD-V3\nMAC: aa:bb:")
    tee.write("cc:dd:ee:ff\n")
    assert record["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert record["chip"] == "ESP32-D0WD-V3"
    assert "MAC: aa:bb:cc:dd:ee:ff" in output.getvalue()


@pytest.fixture
def reporter(tmp_path, monkeypatch):
    report = SessionReport(str(tmp_path / "session.html"))
    info = SimpleNamespace(device="hub", serial_number="USB123", vid=0x1234, pid=0x5678)
    monkeypatch.setattr(
        "openshock_autoflasher.flasher.serial.tools.list_ports.comports", lambda: [info]
    )
    flasher = AutoFlasher(
        board="board",
        hardware_tests=HardwareTestConfig(wifi=True, rf_port="tester"),
        session_report=report,
    )
    monkeypatch.setattr(flasher, "download_firmware", lambda *_: b"firmware")
    monkeypatch.setattr(flasher, "log", lambda *_: None)
    return flasher, report


def test_flash_and_tests_share_one_record_and_capture_mac(reporter):
    flasher, report = reporter

    def esptool_run(_args):
        print("Chip type: ESP32\nMAC: aa:bb:cc:dd:ee:ff")

    def tests(port, config, log, *, on_event):
        on_event(
            "rf_command",
            {
                "remote_id": 123,
                "channel": 1,
                "mode": "Beep",
                "intensity": 0,
                "duration_ms": 1000,
                "status": "passed",
                "detail": "matched",
            },
        )
        return HardwareTestResult(
            port, [CheckResult("wifi", True, "AP seen", 1), CheckResult("rf", True, "matched", 2)]
        )

    with (
        patch("openshock_autoflasher.flasher.esptool.main", side_effect=esptool_run),
        patch("openshock_autoflasher.flasher.run_hardware_tests", side_effect=tests),
    ):
        flasher.flash_device("hub", "1.2.3", "board")
    assert len(report.data["devices"]) == 1
    d = report.data["devices"][0]
    assert d["status"] == "passed" and d["stages"]["flash"] == "passed"
    assert d["mac_address"] == "AA:BB:CC:DD:EE:FF" and d["usb"]["serial_number"] == "USB123"
    assert d["firmware_version"] == "1.2.3" and len(d["firmware_sha256"]) == 64
    assert d["tests"]["wifi"]["status"] == d["tests"]["rf"]["status"] == "passed"
    assert d["rf_commands"][0]["remote_id"] == 123


def test_test_failure_does_not_relabel_successful_flash(reporter):
    flasher, report = reporter
    result = HardwareTestResult(
        "hub", [CheckResult("wifi", True, "seen", 1), CheckResult("rf", False, "missing", 2)]
    )
    with (
        patch.object(flasher, "_run_esptool"),
        patch("openshock_autoflasher.flasher.run_hardware_tests", return_value=result),
    ):
        with pytest.raises(HardwareTestError):
            flasher.flash_device("hub", "1.2.3", "board")
    d = report.data["devices"][0]
    assert d["status"] == "failed" and d["stages"]["flash"] == "passed"
    assert d["tests"]["rf"]["status"] == "failed" and d["tests"]["wifi"]["status"] == "passed"


def test_flash_failure_keeps_identity_and_not_run_tests(reporter):
    flasher, report = reporter

    def fail(_args):
        print("MAC: aa:bb:cc:dd:ee:ff")
        raise RuntimeError("write failed")

    with patch("openshock_autoflasher.flasher.esptool.main", side_effect=fail):
        with pytest.raises(RuntimeError):
            flasher.flash_device("hub", "1.2.3", "board")
    d = report.data["devices"][0]
    assert d["stages"]["flash"] == "failed" and d["status"] == "failed"
    assert d["mac_address"] == "AA:BB:CC:DD:EE:FF"
    assert d["tests"]["wifi"]["status"] == "not_run"


def test_interrupted_test_preserves_completed_checks(reporter):
    flasher, report = reporter

    def interrupted(port, config, log, *, on_event):
        on_event("mac", "AA:BB:CC:DD:EE:FF")
        on_event("check", CheckResult("wifi", True, "seen", 1))
        on_event("start", "rf")
        raise KeyboardInterrupt()

    with patch("openshock_autoflasher.flasher.run_hardware_tests", side_effect=interrupted):
        with pytest.raises(KeyboardInterrupt):
            flasher.test_device("hub")
    d = report.data["devices"][0]
    assert d["status"] == "interrupted" and d["tests"]["rf"]["status"] == "interrupted"
    assert d["tests"]["wifi"]["status"] == "passed"
    report.finish_on_stop()
    assert report.data["status"] == "interrupted"
    assert "AA:BB:CC:DD:EE:FF" in report.path.read_text()


def test_missing_usb_serial_is_unavailable_and_tester_is_not_reported(reporter):
    flasher, report = reporter
    with pytest.raises(HardwareTestError):
        flasher.flash_device("tester", "1", "board")
    assert not report.data["devices"]
    result = HardwareTestResult("other-hub", [CheckResult("wifi", True, "seen", 1)])
    with patch("openshock_autoflasher.flasher.run_hardware_tests", return_value=result):
        flasher.test_device("other-hub")
    assert report.data["devices"][0]["usb"] == {}
    assert "Unavailable" in report.path.read_text()
