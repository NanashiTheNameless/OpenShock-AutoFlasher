"""
Configuration constants for OpenShock Auto-Flasher
"""

# Network and firmware settings
REQUEST_TIMEOUT: int = 30  # seconds
BASE_URL: str = "https://firmware.openshock.org"

# ESP32 flash settings
BAUD_RATE: str = "460800"
FLASH_MODE: str = "dio"
FLASH_FREQ: str = "80m"
FLASH_ADDRESS: str = "0x0000"

# Polling settings
INITIAL_POLL_INTERVAL: float = 0.5  # seconds
MAX_POLL_INTERVAL: float = 1.0  # seconds
POLL_BACKOFF_THRESHOLD: int = 10  # checks before increasing interval
DEVICE_INIT_DELAY: int = 1  # seconds to wait after device detection
