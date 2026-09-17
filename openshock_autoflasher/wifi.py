"""Detect a hub's advertised AP using fresh host-side WiFi scan results."""

import json
import math
import re
import shutil
import subprocess
import sys
import time

import esptool

AP_SSID = re.compile(r"OpenShock-(?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}")


class WiFiScanError(RuntimeError):
    """The host could not verify an access point broadcast."""


def read_ap_ssid(port: str) -> str:
    """The stock firmware appends WiFi.macAddress() (STA/base MAC) to OpenShock-."""
    with esptool.detect_chip(port=port) as device:
        try:
            mac = device.read_mac("BASE_MAC")
            if mac is None or len(mac) != 6:
                raise WiFiScanError("Unable to read a six-byte WiFi MAC from the hub")
            return "OpenShock-" + ":".join(f"{byte:02X}" for byte in mac)
        finally:
            device.hard_reset()


def _run(arguments: list[str], deadline: float) -> str:
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise WiFiScanError("WiFi scan timed out")
    try:
        result = subprocess.run(
            arguments,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=remaining,
            check=False,
        )
    except FileNotFoundError:
        raise WiFiScanError(f"WiFi scan requires {arguments[0]} on PATH") from None
    except subprocess.TimeoutExpired:
        raise WiFiScanError("WiFi scan timed out") from None
    if result.returncode != 0:
        raise WiFiScanError(
            f"{arguments[0]} failed (exit {result.returncode}); check WiFi adapter, permissions and scan service"
        )
    return result.stdout


def scan_ap(
    ssid: str,
    deadline: float,
    *,
    interface: str | None = None,
    command: tuple[str, ...] | None = None,
) -> bool:
    if command is not None:
        output = _run(list(command), deadline)
        try:
            networks = json.loads(output)
        except ValueError:
            raise WiFiScanError(
                "Custom WiFi scan must output a JSON array of SSID strings"
            ) from None
        if not isinstance(networks, list) or any(not isinstance(item, str) for item in networks):
            raise WiFiScanError("Custom WiFi scan must output a JSON array of SSID strings")
        return ssid in networks

    use_networkmanager = (
        sys.platform == "linux" and shutil.which("nmcli") and shutil.which("busctl")
    )
    if sys.platform in ("win32", "darwin", "linux") and not use_networkmanager:
        arguments = [
            sys.executable,
            "-m",
            "openshock_autoflasher.wifi_native",
            "--ssid",
            ssid,
            "--timeout",
            str(max(0, deadline - time.monotonic())),
        ]
        if interface:
            arguments.extend(["--interface", interface])
        try:
            result = json.loads(_run(arguments, deadline))
        except ValueError:
            raise WiFiScanError("WiFi library returned an invalid scan response") from None
        if isinstance(result, dict) and isinstance(result.get("error"), str):
            raise WiFiScanError(result["error"])
        if not isinstance(result, dict) or type(result.get("found")) is not bool:
            raise WiFiScanError("WiFi library returned an invalid scan response")
        return result["found"]

    if sys.platform != "linux":
        raise WiFiScanError(
            "Built-in AP scanning supports Linux, Windows and macOS; supply --test-wifi-scan-command on this platform"
        )

    # NM retains disappeared APs in its cache. Require LastSeen from THIS scan.
    # LastSeen uses integral CLOCK_BOOTTIME seconds, so start on a fresh second.
    now = time.clock_gettime(time.CLOCK_BOOTTIME)
    not_before = math.floor(now) + 1
    if deadline - time.monotonic() <= not_before - now:
        raise WiFiScanError("WiFi scan timed out")
    time.sleep(not_before - now)
    arguments = [
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
    ]
    if interface:
        arguments.extend(["ifname", interface])
    output = _run(arguments, deadline)
    for line in output.splitlines():
        candidate, separator, path = line.rpartition(":")
        if not separator or candidate != ssid:
            continue
        if not re.fullmatch(r"/org/freedesktop/NetworkManager/AccessPoint/\d+", path):
            raise WiFiScanError("NetworkManager returned an invalid access-point path")
        last_seen = _run(
            [
                "busctl",
                "--system",
                "get-property",
                "org.freedesktop.NetworkManager",
                path,
                "org.freedesktop.NetworkManager.AccessPoint",
                "LastSeen",
            ],
            deadline,
        ).strip()
        match = re.fullmatch(r"i (-?\d+)", last_seen)
        if match is None:
            raise WiFiScanError("Cannot verify scan freshness from NetworkManager LastSeen")
        if int(match[1]) >= not_before:
            return True
    return False
