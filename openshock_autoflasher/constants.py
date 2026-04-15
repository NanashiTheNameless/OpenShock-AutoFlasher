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
SUPPORTED_CHIPS: tuple[str, ...] = (
    "esp32",
    "esp32s2",
    "esp32s3",
    "esp32c3",
    "esp32c2",
    "esp32c6",
    "esp32c61",
    "esp32c5",
    "esp32e22",
    "esp32h2",
    "esp32h21",
    "esp32p4",
    "esp32h4",
    "esp32s31",
)

# Polling settings
INITIAL_POLL_INTERVAL: float = 0.5  # seconds
MAX_POLL_INTERVAL: float = 1.0  # seconds
POLL_BACKOFF_THRESHOLD: int = 10  # checks before increasing interval
DEVICE_INIT_DELAY: int = 1  # seconds to wait after device detection
