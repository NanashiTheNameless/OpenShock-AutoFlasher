"""
Tests for constants module
"""

from openshock_autoflasher.constants import (
    REQUEST_TIMEOUT,
    BASE_URL,
    BAUD_RATE,
    FLASH_MODE,
    FLASH_FREQ,
    FLASH_ADDRESS,
    INITIAL_POLL_INTERVAL,
    MAX_POLL_INTERVAL,
    POLL_BACKOFF_THRESHOLD,
    DEVICE_INIT_DELAY,
)


def test_constants_are_defined():
    """Test that all required constants are defined"""
    assert REQUEST_TIMEOUT > 0
    assert BASE_URL.startswith("https://")
    assert BAUD_RATE.isdigit()
    assert FLASH_MODE in ["qio", "qout", "dio", "dout"]
    assert FLASH_FREQ.endswith("m")
    assert FLASH_ADDRESS.startswith("0x")


def test_polling_intervals():
    """Test polling interval constants are logical"""
    assert INITIAL_POLL_INTERVAL > 0
    assert MAX_POLL_INTERVAL >= INITIAL_POLL_INTERVAL
    assert POLL_BACKOFF_THRESHOLD > 0
    assert DEVICE_INIT_DELAY >= 0


def test_flash_address_format():
    """Test flash address is valid hex"""
    assert int(FLASH_ADDRESS, 16) >= 0
