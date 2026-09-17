"""Library-backed scans, run in a child process so native calls have a deadline."""

import argparse
import ctypes
import json
import re
import sys
import time
from typing import Any


def scan_corewlan(ssid: str, interface: str | None) -> bool:
    try:
        import CoreWLAN
    except ImportError:
        raise RuntimeError(
            "Install pyobjc-framework-CoreWLAN in the Auto-Flasher environment"
        ) from None
    client = CoreWLAN.CWWiFiClient.sharedWiFiClient()
    adapters = list(client.interfaces() or [])
    if interface:
        adapters = [adapter for adapter in adapters if adapter.interfaceName() == interface]
    adapters = [adapter for adapter in adapters if adapter.powerOn()]
    if not adapters:
        raise RuntimeError("No enabled macOS WiFi adapter matches the selected interface")
    scanned = False
    for adapter in adapters:
        # This is a blocking directed scan, not cachedScanResults().
        networks, error = adapter.scanForNetworksWithName_error_(ssid, None)
        if error is not None or networks is None:
            continue
        scanned = True
        names = [network.ssid() for network in networks]
        if ssid in names:
            return True
        if names and all(name is None for name in names):
            raise RuntimeError(
                "macOS hid WiFi SSIDs; allow Location Services for your terminal/Python app"
            )
    if not scanned:
        raise RuntimeError(
            "CoreWLAN scan failed; enable WiFi and allow Location Services for your terminal/Python app"
        )
    return False


def _linux_fresh(adapter: Any, ssid: str, started: float) -> bool:
    for network in adapter.scan_results():
        if network.ssid != ssid:
            continue
        if re.fullmatch(r"(?:[\da-fA-F]{2}:){5}[\da-fA-F]{2}", network.bssid) is None:
            raise RuntimeError("pywifi returned an invalid BSSID")
        # pywifi omits age from Profile, so query the same wpa_supplicant socket.
        output = adapter._wifi_ctrl._send_cmd_to_wpas(adapter.name(), "BSS " + network.bssid, True)
        fields = dict(line.split("=", 1) for line in output.splitlines() if "=" in line)
        age = fields.get("age", "")
        if not age.isdigit():
            raise RuntimeError("wpa_supplicant did not provide a usable BSS age")
        # Integral age can round down. Include the full second to reject stale APs.
        if int(age) + 1 <= time.monotonic() - started:
            return True
    return False


def _windows_fresh(adapter: Any, ssid: str, started_filetime: int) -> bool:
    from pywifi import _wifiutil_win as api

    entries = ctypes.pointer(api.WLAN_BSS_LIST())
    code = adapter._wifi_ctrl._wlan_get_network_bss_list(
        adapter._wifi_ctrl._handle, ctypes.byref(adapter._raw_obj["guid"]), ctypes.byref(entries)
    )
    if code:
        raise RuntimeError(
            f"Windows WiFi scan failed (code {code}); enable WLAN AutoConfig and Location access"
        )
    try:
        count = entries.contents.dwNumberOfItems
        offset = api.WLAN_BSS_LIST.wlanBssEntries.offset
        if offset + count * ctypes.sizeof(api.WLAN_BSS_ENTRY) > entries.contents.dwTotalSize:
            raise RuntimeError("Windows returned an invalid WiFi scan buffer")
        rows = ctypes.cast(entries.contents.wlanBssEntries, ctypes.POINTER(api.WLAN_BSS_ENTRY))
        for i in range(count):
            row = rows[i]
            size = row.dot11Ssid.uSSIDLength
            if size <= 32 and bytes(row.dot11Ssid.ucSSID[:size]) == ssid.encode("utf-8"):
                # Windows records the host's beacon/probe receipt time as FILETIME.
                if row.ullHostTimestamp >= started_filetime:
                    return True
        return False
    finally:
        free = api.native_wifi.WlanFreeMemory
        free.argtypes = [ctypes.c_void_p]
        free.restype = None
        free(entries)


def scan_pywifi(ssid: str, interface: str | None, timeout: float) -> bool:
    try:
        import pywifi
    except ImportError:
        raise RuntimeError("Install pywifi in the Auto-Flasher environment") from None
    adapters = pywifi.PyWiFi().interfaces()
    if interface:
        adapters = [adapter for adapter in adapters if adapter.name() == interface]
    if not adapters:
        raise RuntimeError(
            "No WiFi adapters found; check the interface and WiFi service permissions"
        )
    started = time.monotonic()
    filetime = time.time_ns() // 100 + 116444736000000000
    active = []
    for adapter in adapters:
        if sys.platform == "win32":
            code = adapter._wifi_ctrl._wlan_scan(
                adapter._wifi_ctrl._handle, ctypes.byref(adapter._raw_obj["guid"])
            )
            if code:
                continue
        else:
            reply = adapter._wifi_ctrl._send_cmd_to_wpas(adapter.name(), "SCAN", True)
            if reply.strip() != "OK":
                continue
        active.append(adapter)
    if not active:
        raise RuntimeError(
            "WiFi scan request rejected; check adapter power, Location access (Windows), or wpa_supplicant socket permissions (Linux)"
        )
    deadline = started + min(8.0, timeout)
    while time.monotonic() < deadline:
        time.sleep(min(0.25, max(0, deadline - time.monotonic())))
        for adapter in active:
            if sys.platform == "win32":
                found = _windows_fresh(adapter, ssid, filetime)
            else:
                found = _linux_fresh(adapter, ssid, started)
            if found:
                return True
    return False


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--ssid", required=True)
    parser.add_argument("--interface")
    parser.add_argument("--timeout", type=float, required=True)
    args = parser.parse_args()
    try:
        if sys.platform == "darwin":
            found = scan_corewlan(args.ssid, args.interface)
        else:
            found = scan_pywifi(args.ssid, args.interface, args.timeout)
        print(json.dumps({"found": found}))
    except Exception as exc:
        detail = (
            str(exc)
            if isinstance(exc, RuntimeError)
            else f"WiFi library error: {type(exc).__name__}; check adapter and permissions"
        )
        print(json.dumps({"error": detail}))


if __name__ == "__main__":
    main()
