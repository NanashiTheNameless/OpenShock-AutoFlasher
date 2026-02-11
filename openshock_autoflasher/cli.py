"""
Command-line interface for OpenShock Auto-Flasher
"""

import argparse
import signal
import sys
from typing import List

import requests
from rich.style import Style

from .constants import BASE_URL
from .styles import console
from .flasher import AutoFlasher


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


def create_argument_parser(channel: str = "stable") -> argparse.ArgumentParser:
    """Create and return the argument parser with dynamic help text"""
    # Fetch boards for help text using the specified channel
    boards_list = fetch_boards_for_help(channel)
    boards_help = f"Available boards ({channel} channel):\n  " + "\n  ".join(boards_list)

    parser = argparse.ArgumentParser(
        description="OpenShock Auto-Flasher",
        epilog=boards_help,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument(
        "--channel",
        "-c",
        choices=["stable", "beta", "develop"],
        default="stable",
        help="Firmware channel (default: stable)",
    )
    parser.add_argument("--board", "-b", required=True, help="Board type (required)")
    parser.add_argument(
        "--erase",
        "-e",
        action="store_true",
        help="Erase flash before flashing",
    )
    parser.add_argument(
        "--no-auto",
        "-n",
        action="store_true",
        help="Disable auto-flash (just detect devices)",
    )
    parser.add_argument(
        "--post-flash",
        "-p",
        action="append",
        help=(
            "Serial command to send to device after flashing "
            "(can be specified multiple times, executed in order)"
        ),
    )

    return parser


def main() -> None:
    """Main entry point for the application"""

    # Set up signal handler for clean exit on Ctrl+C
    def signal_handler(sig: int, frame: object) -> None:
        console.print("\n")
        console.print(
            "Exiting...",
            style=Style(color="white"),
            markup=False,
            highlight=False,
        )
        sys.exit(0)  # Clean exit with proper cleanup

    signal.signal(signal.SIGINT, signal_handler)

    # Parse channel early to fetch correct boards list for help text
    channel = "stable"
    for i, arg in enumerate(sys.argv):
        if arg in ["--channel", "-c"] and i + 1 < len(sys.argv):
            candidate = sys.argv[i + 1]
            if candidate in ["stable", "beta", "develop"]:
                channel = candidate
                break

    # Create parser with dynamic help
    parser = create_argument_parser(channel)

    # Show help if no arguments provided
    if len(sys.argv) == 1:
        parser.print_help()
        sys.exit(0)

    args = parser.parse_args()

    flasher = AutoFlasher(
        channel=args.channel,
        board=args.board,
        erase_flash=args.erase,
        auto_flash=not args.no_auto,
        post_flash_commands=args.post_flash or [],
    )

    flasher.run()


if __name__ == "__main__":
    main()
