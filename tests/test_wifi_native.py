"""Cross-platform library adapters without WiFi hardware or OS frameworks."""

import ctypes
import json
import sys
from types import SimpleNamespace
from unittest.mock import Mock

import pytest

from openshock_autoflasher import wifi_native as native

SSID = "OpenShock-AA:BB:CC:DD:EE:FF"


def mac_adapter(monkeypatch, names):
    adapter = Mock()
    adapter.interfaceName.return_value = "en0"
    adapter.powerOn.return_value = True
    adapter.scanForNetworksWithName_error_.return_value = (
        [Mock(ssid=Mock(return_value=name)) for name in names],
        None,
    )
    module = Mock()
    module.CWWiFiClient.sharedWiFiClient.return_value.interfaces.return_value = [adapter]
    monkeypatch.setitem(sys.modules, "CoreWLAN", module)
    return adapter


@pytest.mark.parametrize("names,found", [([SSID], True), ([SSID + "-other"], False), ([], False)])
def test_corewlan_runs_directed_scan_and_matches_exact_ssid(monkeypatch, names, found):
    adapter = mac_adapter(monkeypatch, names)
    assert native.scan_corewlan(SSID, "en0") is found
    adapter.scanForNetworksWithName_error_.assert_called_once_with(SSID, None)
    adapter.cachedScanResults.assert_not_called()


def test_corewlan_reports_redacted_ssids_and_missing_interface(monkeypatch):
    mac_adapter(monkeypatch, [None])
    with pytest.raises(RuntimeError, match="Location"):
        native.scan_corewlan(SSID, None)
    with pytest.raises(RuntimeError, match="No enabled"):
        native.scan_corewlan(SSID, "en9")


def test_corewlan_reports_scan_error(monkeypatch):
    adapter = mac_adapter(monkeypatch, [])
    adapter.scanForNetworksWithName_error_.return_value = (None, "permission error")
    with pytest.raises(RuntimeError, match="CoreWLAN scan failed"):
        native.scan_corewlan(SSID, None)


@pytest.mark.parametrize(
    "age,elapsed,found", [("0", 0.5, False), ("0", 1.1, True), ("2", 2.5, False), ("9", 2.5, False)]
)
def test_linux_bss_age_rejects_cached_and_ambiguous_results(monkeypatch, age, elapsed, found):
    adapter = Mock()
    adapter.scan_results.return_value = [SimpleNamespace(ssid=SSID, bssid="aa:bb:cc:dd:ee:ff")]
    adapter._wifi_ctrl._send_cmd_to_wpas.return_value = f"ssid={SSID}\nage={age}\n"
    monkeypatch.setattr(native.time, "monotonic", lambda: 100 + elapsed)
    assert native._linux_fresh(adapter, SSID, 100) is found


def test_linux_missing_age_fails_closed():
    adapter = Mock()
    adapter.scan_results.return_value = [SimpleNamespace(ssid=SSID, bssid="aa:bb:cc:dd:ee:ff")]
    adapter._wifi_ctrl._send_cmd_to_wpas.return_value = "ssid=" + SSID
    with pytest.raises(RuntimeError, match="BSS age"):
        native._linux_fresh(adapter, SSID, 100)


@pytest.mark.parametrize("timestamp,expected", [(999, False), (1000, True), (1001, True)])
def test_windows_checks_beacon_timestamp_and_frees_results(monkeypatch, timestamp, expected):
    class DotSSID(ctypes.Structure):
        _fields_ = [("uSSIDLength", ctypes.c_uint32), ("ucSSID", ctypes.c_char * 32)]

    class Entry(ctypes.Structure):
        _fields_ = [("dot11Ssid", DotSSID), ("ullHostTimestamp", ctypes.c_uint64)]

    class BssList(ctypes.Structure):
        _fields_ = [
            ("dwTotalSize", ctypes.c_uint32),
            ("dwNumberOfItems", ctypes.c_uint32),
            ("wlanBssEntries", Entry * 1),
        ]

    blob = BssList()
    blob.dwTotalSize = ctypes.sizeof(blob)
    blob.dwNumberOfItems = 1
    blob.wlanBssEntries[0].dot11Ssid.uSSIDLength = len(SSID)
    blob.wlanBssEntries[0].dot11Ssid.ucSSID = SSID.encode()
    blob.wlanBssEntries[0].ullHostTimestamp = timestamp
    free = Mock()
    api = SimpleNamespace(
        WLAN_BSS_LIST=BssList,
        WLAN_BSS_ENTRY=Entry,
        native_wifi=SimpleNamespace(WlanFreeMemory=free),
    )
    monkeypatch.setitem(sys.modules, "pywifi", SimpleNamespace(_wifiutil_win=api))
    adapter = Mock()
    adapter._raw_obj = {"guid": ctypes.c_uint32(1)}

    def get_results(handle, guid, output):
        ctypes.cast(output, ctypes.POINTER(ctypes.POINTER(BssList)))[0] = ctypes.pointer(blob)
        return 0

    adapter._wifi_ctrl._wlan_get_network_bss_list.side_effect = get_results
    assert native._windows_fresh(adapter, SSID, 1000) is expected
    free.assert_called_once()


def test_pywifi_scan_request_must_succeed(monkeypatch):
    adapter = Mock()
    adapter._wifi_ctrl._send_cmd_to_wpas.return_value = "FAIL\n"
    module = Mock()
    module.PyWiFi.return_value.interfaces.return_value = [adapter]
    monkeypatch.setitem(sys.modules, "pywifi", module)
    monkeypatch.setattr(native.sys, "platform", "linux")
    with pytest.raises(RuntimeError, match="request rejected"):
        native.scan_pywifi(SSID, None, 1)


def test_worker_returns_json_error_instead_of_false_success(monkeypatch, capsys):
    monkeypatch.setattr(sys, "argv", ["worker", "--ssid", SSID, "--timeout", "1"])
    monkeypatch.setattr(native.sys, "platform", "darwin")
    monkeypatch.setattr(
        native, "scan_corewlan", Mock(side_effect=RuntimeError("permission denied"))
    )
    native.main()
    assert json.loads(capsys.readouterr().out) == {"error": "permission denied"}
