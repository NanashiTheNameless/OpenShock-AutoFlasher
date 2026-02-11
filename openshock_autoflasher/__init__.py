"""
OpenShock Auto-Flasher
Automatically flashes OpenShock hubs when plugged in
Background colors indicate status:
Blue=Waiting, Yellow=Flashing, Green=Done, Red=Error
"""

from openshock_autoflasher.flasher import AutoFlasher
from openshock_autoflasher.constants import BASE_URL, BAUD_RATE

__all__ = ["AutoFlasher", "BASE_URL", "BAUD_RATE"]
