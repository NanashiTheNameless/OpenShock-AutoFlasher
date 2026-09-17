"""One durable, self-contained HTML report for an entire device session."""

from contextlib import redirect_stdout
from datetime import datetime, timezone
from html import escape
import json
import importlib.metadata
import os
import platform
from pathlib import Path
import re
import sys
import tempfile
import time
from typing import Any
from uuid import uuid4

REPORT_STYLE = """
:root{color-scheme:dark;background:#0b1220;color:#e2e8f0}
body{font:16px/1.5 system-ui,sans-serif;max-width:1200px;margin:2rem auto;padding:0 1rem}
table{border-collapse:collapse;width:100%;margin:1rem 0}
th,td{border:1px solid #334155;padding:.5rem;text-align:left;vertical-align:top}
th{background:#1e293b;color:#f1f5f9}
td{background:#111b2e;overflow-wrap:anywhere}
details{background:#111b2e;border:1px solid #334155;border-radius:8px;margin:1rem 0;padding:1rem}
summary{cursor:pointer;font-weight:600}
summary:focus-visible{outline:2px solid #93c5fd;outline-offset:4px}
pre{background:#0b1220;border-radius:6px;padding:1rem;white-space:pre-wrap;overflow-wrap:anywhere}
a{color:#93c5fd}
::selection{background:#345279;color:#fff}
.status{display:inline-block;border:1px solid currentColor;border-radius:4px;padding:.05rem .4rem;font-weight:600}
.passed,.completed{color:#86efac;background:#123127}
.failed{color:#fda4af;background:#3b1825}
.interrupted{color:#fcd34d;background:#352b16}
.running,.in_progress{color:#93c5fd;background:#182e49}
.skipped,.not_run,.not_requested,.disabled{color:#cbd5e1;background:#243044}
"""


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


class SessionReport:
    def __init__(self, path: str | None = None, *, settings: dict[str, Any] | None = None):
        self.session_id = uuid4().hex
        name = f"OpenShock-session-{datetime.now():%Y%m%d-%H%M%S}-{self.session_id[:8]}.html"
        self.path = Path(path or name).expanduser().absolute()
        self.data: dict[str, Any] = {
            "session_id": self.session_id,
            "started_at": utc_now(),
            "finished_at": None,
            "status": "running",
            "settings": settings or {},
            "devices": [],
        }
        self._starts: dict[int, float] = {}
        self.data["settings"].update(
            host_platform=platform.platform(), python_version=platform.python_version()
        )
        for package in ("OpenShock-AutoFlasher", "esptool", "pywifi", "pyobjc-framework-CoreWLAN"):
            try:
                self.data["settings"][package + "_version"] = importlib.metadata.version(package)
            except importlib.metadata.PackageNotFoundError:
                pass
        # Never overwrite another session or an unrelated existing file.
        with self.path.open("x", encoding="utf-8") as output:
            output.write(self.render())

    def start_device(
        self,
        port: str,
        *,
        board: str | None,
        mode: str,
        firmware: str | None,
        tests: dict[str, bool],
        usb: dict[str, Any],
    ) -> dict[str, Any]:
        number = len(self.data["devices"]) + 1
        device: dict[str, Any] = {
            "attempt": number,
            "port": port,
            "board": board,
            "mode": mode,
            "firmware_version": firmware,
            "mac_address": None,
            "mac_source": None,
            "chip": None,
            "usb": usb,
            "started_at": utc_now(),
            "finished_at": None,
            "elapsed_seconds": None,
            "status": "in_progress",
            "stages": {
                "download": "not_run" if mode == "flash" else "skipped",
                "flash": "not_run" if mode == "flash" else "skipped",
                "erase": "not_requested",
                "post_flash": "not_requested",
            },
            "tests": {
                name: {"status": "not_run" if enabled else "disabled"}
                for name, enabled in tests.items()
            },
            "rf_commands": [],
            "retries": [],
            "warnings": [],
            "error": None,
        }
        self.data["devices"].append(device)
        self._starts[number] = time.monotonic()
        self.save()
        return device

    def finish_device(self, device: dict[str, Any], status: str, error: str | None = None) -> None:
        device.update(
            status=status,
            error=error,
            finished_at=utc_now(),
            elapsed_seconds=round(time.monotonic() - self._starts[device["attempt"]], 3),
        )
        for stage, value in device["stages"].items():
            if value == "in_progress":
                device["stages"][stage] = "interrupted" if status == "interrupted" else "failed"
        for value in device["tests"].values():
            if value["status"] == "in_progress":
                value["status"] = "interrupted" if status == "interrupted" else "failed"
        self.save()

    def finish(self, status: str = "completed") -> None:
        if self.data["finished_at"] is None:
            self.data.update(status=status, finished_at=utc_now())
            self.save()

    def finish_on_stop(self) -> None:
        """Treat stopping between devices as a normal end to a batch."""
        interrupted = any(
            device["status"] in ("in_progress", "interrupted") for device in self.data["devices"]
        )
        self.finish("interrupted" if interrupted else "completed")

    def save(self) -> None:
        """Replace the same report atomically, preserving the previous copy on error."""
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=self.path.parent,
                prefix=".openshock-report-",
                delete=False,
            ) as output:
                temporary = Path(output.name)
                output.write(self.render())
                output.flush()
                os.fsync(output.fileno())
            os.replace(temporary, self.path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def render(self) -> str:
        def text(value: Any) -> str:
            return escape("Unavailable" if value is None else str(value))

        def status(value: Any) -> str:
            known = {
                "passed",
                "completed",
                "failed",
                "interrupted",
                "running",
                "in_progress",
                "skipped",
                "not_run",
                "not_requested",
                "disabled",
            }
            if isinstance(value, str) and value in known:
                return f"<span class='status {value}'>{text(value.replace('_', ' '))}</span>"
            return text(value)

        def table(rows: list[tuple[str, Any]]) -> str:
            return (
                "<table>"
                + "".join(
                    f"<tr><th>{text(key)}</th><td>{status(value) if key == 'Status' else text(value)}</td></tr>"
                    for key, value in rows
                )
                + "</table>"
            )

        devices = self.data["devices"]
        passed = sum(d["status"] == "passed" for d in devices)
        failed = sum(d["status"] == "failed" for d in devices)
        flashed = sum(d["stages"].get("flash") == "passed" for d in devices)
        body = [
            "<!doctype html><html lang='en'><meta charset='utf-8'>",
            "<meta name='viewport' content='width=device-width, initial-scale=1'>",
            "<meta name='color-scheme' content='dark'>",
            "<title>OpenShock session report</title><style>",
            REPORT_STYLE,
            "</style><h1>OpenShock session report</h1>",
            table(
                [
                    ("Session", self.session_id),
                    ("Status", self.data["status"]),
                    ("Started (UTC)", self.data["started_at"]),
                    ("Finished (UTC)", self.data["finished_at"]),
                ]
            ),
            f"<p>{len(devices)} attempts; {flashed} flashed; {passed} passed; {failed} failed.</p>",
            "<p>Each connection attempt has its own record. USB serial numbers identify the USB adapter; some adapters do not provide one.</p>",
            "<table><thead><tr><th>Attempt</th><th>Port</th><th>MAC address</th><th>USB serial number</th><th>Firmware</th><th>Flash</th><th>Overall</th></tr></thead><tbody>",
        ]
        for d in devices:
            values = [
                d["attempt"],
                d["port"],
                d["mac_address"],
                d["usb"].get("serial_number"),
                d["firmware_version"],
                d["stages"].get("flash", "not_run"),
                d["status"],
            ]
            body.append(
                "<tr>"
                + "".join(
                    f"<td>{status(v) if i >= 5 else text(v)}</td>" for i, v in enumerate(values)
                )
                + "</tr>"
            )
        body.append("</tbody></table>")
        for d in devices:
            body.append(
                f"<details open><summary>Attempt {d['attempt']}: {text(d['port'])} - {status(d['status'])}</summary>"
            )
            body.append(
                table(
                    [
                        (key.replace("_", " ").title(), d.get(key))
                        for key in (
                            "mac_address",
                            "mac_source",
                            "board",
                            "chip",
                            "mode",
                            "firmware_version",
                            "firmware_sha256",
                            "firmware_size_bytes",
                            "started_at",
                            "finished_at",
                            "elapsed_seconds",
                            "error",
                        )
                    ]
                )
            )
            body.append(
                "<h3>Tests</h3><table><tr><th>Test</th><th>Status</th><th>Seconds</th><th>Detail</th></tr>"
            )
            for name, result in d["tests"].items():
                body.append(
                    "<tr>"
                    + "".join(
                        f"<td>{status(v) if i == 1 else text(v)}</td>"
                        for i, v in enumerate(
                            (
                                name,
                                result["status"],
                                result.get("elapsed_seconds"),
                                result.get("detail", ""),
                            )
                        )
                    )
                    + "</tr>"
                )
            body.append(
                "</table><h3>RF commands</h3><table><tr><th>ID</th><th>Channel</th><th>Mode</th><th>Intensity</th><th>Duration (ms)</th><th>Status</th><th>Detail</th></tr>"
            )
            for case in d["rf_commands"]:
                body.append(
                    "<tr>"
                    + "".join(
                        f"<td>{status(case.get(k)) if k == 'status' else text(case.get(k))}</td>"
                        for k in (
                            "remote_id",
                            "channel",
                            "mode",
                            "intensity",
                            "duration_ms",
                            "status",
                            "detail",
                        )
                    )
                    + "</tr>"
                )
            body.append(
                "</table><details><summary>All device data</summary><pre>"
                + escape(json.dumps(d, indent=2, ensure_ascii=True))
                + "</pre></details></details>"
            )
        body.append(
            "<details><summary>Session settings</summary><pre>"
            + escape(json.dumps(self.data["settings"], indent=2, ensure_ascii=True))
            + "</pre></details></html>"
        )
        return "\n".join(body)


class IdentityOutput:
    """Tee esptool output, retaining identity fields rather than raw serial logs."""

    def __init__(self, stream: Any, device: dict[str, Any]):
        self.stream = stream
        self.device = device
        self.pending = ""

    def __getattr__(self, name: str) -> Any:
        return getattr(self.stream, name)

    def write(self, data: str) -> int:
        result = self.stream.write(data)
        clean = re.sub(r"\x1b\[[0-?]*[ -/]*[@-~]", "", data)
        self.pending += clean
        lines = self.pending.replace("\r", "\n").split("\n")
        self.pending = lines.pop()[-4096:]
        for line in lines:
            match = re.fullmatch(r"\s*MAC:\s*((?:[\da-fA-F]{2}:){5}[\da-fA-F]{2})\s*", line)
            if match:
                self.device["mac_address"] = match[1].upper()
                self.device["mac_source"] = "esptool"
            if line.strip().startswith("Chip type:"):
                self.device["chip"] = line.split("Chip type:", 1)[1].strip()
        return result

    def flush(self) -> None:
        self.stream.flush()


def capture_identity(device: dict[str, Any]):
    return redirect_stdout(IdentityOutput(sys.stdout, device))
