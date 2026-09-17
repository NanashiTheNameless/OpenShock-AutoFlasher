"""Host-side AP scan parsing, freshness and device identity checks."""

import json
import subprocess
from unittest.mock import MagicMock, Mock

import pytest

from openshock_autoflasher import wifi

SSID = "OpenShock-AA:BB:CC:DD:EE:FF"
AP_PATH = "/org/freedesktop/NetworkManager/AccessPoint/7"


@pytest.fixture
def scanner(monkeypatch):
    monkeypatch.setattr(wifi.sys, "platform", "linux")
    monkeypatch.setattr(wifi.shutil, "which", lambda name: name)
    monkeypatch.setattr(wifi.time, "clock_gettime", lambda _: 100.5, raising=False)
    monkeypatch.setattr(wifi.time, "CLOCK_BOOTTIME", 7, raising=False)
    monkeypatch.setattr(wifi.time, "monotonic", lambda: 10.0)
    monkeypatch.setattr(wifi.time, "sleep", lambda _: None)
    process = Mock()
    monkeypatch.setattr(wifi.subprocess, "run", process)
    return process


def response(output, code=0):
    return subprocess.CompletedProcess([], code, stdout=output, stderr="")


def test_host_scan_matches_mac_and_fresh_observation(scanner):
    scanner.side_effect = [response(f"{SSID}:{AP_PATH}\n"), response("i 101\n")]
    assert wifi.scan_ap(SSID, 30.0, interface="wlan0")
    assert scanner.call_args_list[0].args[0] == [
        "nmcli",
        "--terse",
        "--escape",
        "no",
        "--fields",
        "SSID,DBUS-PATH",
        "device",
        "wifi",
        "list",
        "--rescan",
        "yes",
        "ifname",
        "wlan0",
    ]
    assert scanner.call_args_list[1].args[0][-1] == "LastSeen"


@pytest.mark.parametrize("last_seen", ["i 100\n", "i -1\n"])
def test_cached_ap_does_not_pass(scanner, last_seen):
    scanner.side_effect = [response(f"{SSID}:{AP_PATH}\n"), response(last_seen)]
    assert not wifi.scan_ap(SSID, 30.0)


def test_other_openshock_hub_does_not_pass(scanner):
    scanner.return_value = response(f"OpenShock-11:22:33:44:55:66:{AP_PATH}\n")
    assert not wifi.scan_ap(SSID, 30.0)
    assert scanner.call_count == 1


@pytest.mark.parametrize("output", ["unknown", "u 101", "i 101 extra"])
def test_invalid_freshness_response_is_failure(scanner, output):
    scanner.side_effect = [response(f"{SSID}:{AP_PATH}\n"), response(output)]
    with pytest.raises(wifi.WiFiScanError, match="freshness"):
        wifi.scan_ap(SSID, 30.0)


@pytest.mark.parametrize(
    "failure",
    [
        FileNotFoundError(),
        subprocess.TimeoutExpired("nmcli", 5),
    ],
)
def test_scan_tool_errors(scanner, failure):
    scanner.side_effect = failure
    with pytest.raises(wifi.WiFiScanError):
        wifi.scan_ap(SSID, 30.0)


def test_scan_nonzero_exit_is_failure(scanner):
    scanner.return_value = response("", 1)
    with pytest.raises(wifi.WiFiScanError, match="permissions"):
        wifi.scan_ap(SSID, 30.0)


def test_custom_scanner_uses_argument_array_and_exact_ssid(scanner):
    scanner.return_value = response(json.dumps([SSID]))
    assert wifi.scan_ap(SSID, 30.0, command=("python", "scan wifi.py"))
    assert scanner.call_args.args[0] == ["python", "scan wifi.py"]
    assert scanner.call_args.kwargs.get("shell", False) is False
    scanner.return_value = response(json.dumps([SSID + "-other"]))
    assert not wifi.scan_ap(SSID, 30.0, command=("scanner",))


@pytest.mark.parametrize("output", ["no JSON", "{}", "[1]", '"an SSID"'])
def test_custom_scanner_rejects_invalid_output(scanner, output):
    scanner.return_value = response(output)
    with pytest.raises(wifi.WiFiScanError, match="JSON array"):
        wifi.scan_ap(SSID, 30.0, command=("scanner",))


def test_unsupported_host_reports_custom_scanner_option(scanner, monkeypatch):
    monkeypatch.setattr(wifi.sys, "platform", "freebsd")
    with pytest.raises(wifi.WiFiScanError, match="test-wifi-scan-command"):
        wifi.scan_ap(SSID, 30.0)
    scanner.assert_not_called()


def test_mac_is_read_from_target_and_hub_resets(monkeypatch):
    device = MagicMock()
    device.__enter__.return_value = device
    device.read_mac.return_value = bytes.fromhex("AABBCCDDEEFF")
    detect = Mock(return_value=device)
    monkeypatch.setattr(wifi.esptool, "detect_chip", detect)
    assert wifi.read_ap_ssid("dut") == SSID
    detect.assert_called_once_with(port="dut")
    device.read_mac.assert_called_once_with("BASE_MAC")
    device.hard_reset.assert_called_once()
    device.__exit__.assert_called_once()


def test_mac_read_failure_still_resets_and_closes(monkeypatch):
    device = MagicMock()
    device.__enter__.return_value = device
    device.read_mac.return_value = None
    monkeypatch.setattr(wifi.esptool, "detect_chip", Mock(return_value=device))
    with pytest.raises(wifi.WiFiScanError):
        wifi.read_ap_ssid("dut")
    device.hard_reset.assert_called_once()
    device.__exit__.assert_called_once()


@pytest.mark.parametrize("platform", ["win32", "darwin", "linux"])
def test_library_scanner_is_selected_and_bounded(scanner, monkeypatch, platform):
    monkeypatch.setattr(wifi.sys, "platform", platform)
    monkeypatch.setattr(wifi.shutil, "which", lambda _: None)
    scanner.return_value = response('{"found": true}')
    assert wifi.scan_ap(SSID, 30, interface="adapter")
    args = scanner.call_args.args[0]
    assert args[:3] == [wifi.sys.executable, "-m", "openshock_autoflasher.wifi_native"]
    assert args[-2:] == ["--interface", "adapter"]
    assert scanner.call_args.kwargs["timeout"] == 20


@pytest.mark.parametrize(
    "output", ['{"found": "yes"}', "[]", "bad JSON", '{"error": "permission denied"}']
)
def test_library_scanner_errors_cannot_pass(scanner, monkeypatch, output):
    monkeypatch.setattr(wifi.sys, "platform", "darwin")
    scanner.return_value = response(output)
    with pytest.raises(wifi.WiFiScanError):
        wifi.scan_ap(SSID, 30)
