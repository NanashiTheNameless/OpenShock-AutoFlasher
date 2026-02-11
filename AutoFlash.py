#!/usr/bin/env python3
"""
OpenShock Auto-Flasher
Automatically flashes OpenShock hubs when plugged in
Background colors indicate status: Blue=Waiting, Yellow=Flashing, Green=Done, Red=Error
"""

from openshock_autoflasher.cli import main

if __name__ == "__main__":
    main()
