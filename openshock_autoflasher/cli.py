"""
Command-line interface for OpenShock Auto-Flasher
"""

import argparse
import math
import json
import signal
import sys
from typing import List

import requests
from rich.style import Style

from .constants import BASE_URL, SUPPORTED_CHIPS
from .styles import console
from .flasher import AutoFlasher
from .hardware_tests import HardwareTestConfig, same_port
from .report import SessionReport


def non_negative_float(value: str) -> float:
    """Parse a non-negative float argument value."""
    parsed_value = float(value)
    if parsed_value < 0:
        raise argparse.ArgumentTypeError("must be non-negative")
    return parsed_value


def positive_float(value: str) -> float:
    parsed = float(value)
    if not math.isfinite(parsed) or parsed <= 0:
        raise argparse.ArgumentTypeError("must be finite and greater than zero")
    return parsed


def fetch_boards_for_help(channel: str = "stable") -> List[str]:
    """Fetch boards list for help text"""
    try:
        version_url = f"{BASE_URL}/version-{channel}.txt"
        response = requests.get(version_url, timeout=5)
        response.raise_for_status()
        version = response.text.strip()

        boards_url = f"{BASE_URL}/{version}/boards.txt"
        response = requests.get(boards_url, timeout=5)
        response.raise_for_status()
        boards = [line.strip() for line in response.text.strip().split("\n")]
        return boards
    except Exception:
        return ["(Unable to fetch boards list - check network connection)"]


def create_argument_parser(
    channel: str = "stable", include_boards: bool = True
) -> argparse.ArgumentParser:
    """Create and return the argument parser with dynamic help text"""
    # Fetch boards for help text using the specified channel
    boards_list = fetch_boards_for_help(channel) if include_boards else []
    boards_help = f"Available boards ({channel} channel):\n  " + "\n  ".join(boards_list)

    parser = argparse.ArgumentParser(
        description="OpenShock Auto-Flasher",
        epilog=boards_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--channel",
        "-C",
        choices=["stable", "beta", "develop"],
        default="stable",
        help="Firmware channel (default: stable)",
    )
    parser.add_argument(
        "--version",
        "-V",
        help="Use specific firmware version (overrides channel selection)",
    )
    parser.add_argument("--board", "-B", required=True, help="Board type (required)")
    parser.add_argument(
        "--chip",
        choices=("auto", *SUPPORTED_CHIPS),
        default="auto",
        help="Target chip for esptool (default: auto)",
    )
    parser.add_argument(
        "--erase",
        "-E",
        action="store_true",
        help="Erase flash before flashing",
    )
    parser.add_argument(
        "--no-auto",
        "-N",
        action="store_true",
        help="Disable auto-flash (just detect devices)",
    )
    parser.add_argument(
        "--post-flash",
        "-P",
        action="append",
        help=(
            "Serial command to send to device after flashing "
            "(can be specified multiple times, executed in order)"
        ),
    )
    parser.add_argument(
        "--post-flash-delay",
        type=non_negative_float,
        default=0.0,
        metavar="milliseconds",
        help="Milliseconds to wait between post-flash commands (default: 0)",
    )
    parser.add_argument(
        "--alert",
        "-A",
        action="store_true",
        help="Beep audibly when flashing completes",
    )

    parser.add_argument("--port", help="Process this device once, then exit (COM3 or /dev/ttyUSB0)")
    reports = parser.add_mutually_exclusive_group()
    reports.add_argument(
        "--report",
        metavar="PATH",
        help="Session HTML report path (default: timestamped file in current directory)",
    )
    reports.add_argument("--no-report", action="store_true", help="Disable the session report")
    parser.add_argument(
        "--test-only",
        action="store_true",
        help="Test existing firmware on newly connected hubs; --port tests one hub",
    )
    tests = parser.add_argument_group("Automated hardware testing")
    tests.add_argument(
        "--test-wifi",
        action="store_true",
        help="Verify the hub broadcasts its OpenShock-MAC access point",
    )
    tests.add_argument(
        "--test-wifi-ssid",
        help="Explicit expected OpenShock-MAC SSID (otherwise read hub MAC with esptool)",
    )
    tests.add_argument(
        "--test-wifi-interface",
        help="WiFi adapter name (Linux/macOS) or description (Windows); default: all adapters",
    )
    tests.add_argument(
        "--test-wifi-scan-command",
        type=json.loads,
        metavar="JSON_ARGV",
        help="Custom fresh WiFi scan command as a JSON argument array; stdout must be a JSON SSID array",
    )
    rf = tests.add_mutually_exclusive_group()
    rf.add_argument(
        "--test-rf",
        action="store_true",
        help="Auto-detect the RF tester's serial port; plug the tester in before any hubs",
    )
    rf.add_argument("--test-rf-port", help="Separate CaiXianlinRemoteIDMonitor serial port")
    tests.add_argument(
        "--test-timeout",
        type=positive_float,
        default=60.0,
        metavar="SECONDS",
        help="Timeout per hardware test operation (default: 60)",
    )
    tests.add_argument(
        "--factory-reset-after-test",
        action="store_true",
        help="Send factoryreset after tests (pass or fail), clearing hub settings and restarting",
    )
    return parser


def main() -> None:
    """Main entry point for the application"""

    # Set up signal handler for clean exit on Ctrl+C
    def signal_handler(sig: int, frame: object) -> None:
        # esptool treats SystemExit(0) as success; preserve cancellation instead.
        raise KeyboardInterrupt()

    signal.signal(signal.SIGINT, signal_handler)

    # Parse channel early to fetch correct boards list for help text
    channel = "stable"
    for i, arg in enumerate(sys.argv):
        if arg in ["--channel", "-C"] and i + 1 < len(sys.argv):
            candidate = sys.argv[i + 1]
            if candidate in ["stable", "beta", "develop"]:
                channel = candidate
                break

    # Create parser with dynamic help
    parser = create_argument_parser(
        channel,
        include_boards=len(sys.argv) == 1 or any(arg in ("--help", "-h") for arg in sys.argv),
    )

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    testing = args.test_wifi or args.test_rf or args.test_rf_port is not None
    if args.test_only and not testing:
        parser.error("--test-only requires at least one WiFi or RF test")
    if args.no_auto and (testing or args.port):
        parser.error("--no-auto cannot be combined with hardware tests or --port")
    if args.port and args.test_rf_port and same_port(args.port, args.test_rf_port):
        parser.error("--port and --test-rf-port must refer to separate devices")
    if not args.test_wifi and any(
        value is not None
        for value in (args.test_wifi_ssid, args.test_wifi_interface, args.test_wifi_scan_command)
    ):
        parser.error("WiFi scan options require --test-wifi")
    if args.test_wifi_scan_command is not None and (
        not isinstance(args.test_wifi_scan_command, list)
        or not args.test_wifi_scan_command
        or any(not isinstance(arg, str) or not arg for arg in args.test_wifi_scan_command)
    ):
        parser.error("--test-wifi-scan-command must be a nonempty JSON array of nonempty strings")
    try:
        hardware_tests = HardwareTestConfig(
            wifi=args.test_wifi,
            wifi_ssid=args.test_wifi_ssid,
            wifi_interface=args.test_wifi_interface,
            wifi_scan_command=(
                tuple(args.test_wifi_scan_command) if args.test_wifi_scan_command else None
            ),
            rf_port=args.test_rf_port,
            rf_auto_detect=args.test_rf,
            timeout=args.test_timeout,
            factory_reset_after_test=args.factory_reset_after_test,
        )
    except ValueError as exc:
        parser.error(str(exc))

    report = None
    if not args.no_report and not args.no_auto:
        try:
            report = SessionReport(
                args.report,
                settings={
                    "board": args.board,
                    "channel": args.channel,
                    "test_only": args.test_only,
                    "erase": args.erase,
                    "wifi": args.test_wifi,
                    "rf": hardware_tests.rf_enabled,
                    "factory_reset_after_test": args.factory_reset_after_test,
                    "test_timeout_seconds": args.test_timeout,
                    "post_flash_command_count": len(args.post_flash or []),
                },
            )
        except OSError as exc:
            parser.error(f"Cannot create session report: {exc}")
    status = "completed"
    try:
        flasher = AutoFlasher(
            channel=args.channel,
            board=args.board,
            erase_flash=args.erase,
            auto_flash=not args.no_auto,
            post_flash_commands=args.post_flash or [],
            post_flash_delay=args.post_flash_delay,
            alert=args.alert,
            version=args.version,
            chip=args.chip,
            hardware_tests=hardware_tests,
            test_only=args.test_only,
            session_report=report,
        )

        if report is not None:
            flasher.log(f"Session report: {report.path}")

        if args.port:
            flasher.log_test_settings()
            try:
                flasher.prepare_rf_monitor(target_port=args.port)
                if args.test_only:
                    flasher.test_device(args.port)
                else:
                    version = flasher.fetch_version()
                    if args.board not in flasher.fetch_boards(version):
                        raise ValueError(
                            f"Board '{args.board}' is not available for version {version}"
                        )
                    flasher.flash_device(args.port, version, args.board)
            except Exception as exc:
                flasher.set_state("error")
                flasher.log(f"Failed: {exc}")
                sys.exit(1)
            return
        flasher.run()
    except (KeyboardInterrupt, SystemExit) as exc:
        if isinstance(exc, SystemExit) and exc.code:
            status = "failed"
        elif report is not None:
            report.finish_on_stop()
        if isinstance(exc, KeyboardInterrupt):
            console.print("\nExiting...", style=Style(color="white"), markup=False, highlight=False)
            sys.exit(0)
        raise
    except Exception:
        status = "failed"
        raise
    finally:
        if report is not None:
            report.finish(status)


if __name__ == "__main__":
    main()
