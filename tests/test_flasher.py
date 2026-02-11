"""
Tests for flasher module
"""

import pytest
from unittest.mock import Mock, patch, MagicMock

from openshock_autoflasher.flasher import AutoFlasher


@pytest.fixture
def flasher():
    """Create a basic AutoFlasher instance for testing"""
    return AutoFlasher(
        channel="stable",
        board="test-board",
        erase_flash=False,
        auto_flash=True,
        post_flash_commands=[],
    )


def test_flasher_initialization(flasher):
    """Test AutoFlasher initialization"""
    assert flasher.channel == "stable"
    assert flasher.board == "test-board"
    assert flasher.erase_flash is False
    assert flasher.auto_flash is True
    assert flasher.post_flash_commands == []
    assert flasher.state == "waiting"
    assert flasher.version_cache is None
    assert flasher.boards_cache is None


def test_get_style(flasher):
    """Test style getter returns correct styles"""
    from openshock_autoflasher.styles import StateColors

    flasher.state = "waiting"
    assert flasher.get_style() == StateColors.WAITING

    flasher.state = "flashing"
    assert flasher.get_style() == StateColors.FLASHING

    flasher.state = "done"
    assert flasher.get_style() == StateColors.DONE

    flasher.state = "error"
    assert flasher.get_style() == StateColors.ERROR


def test_set_state(flasher):
    """Test state setter updates both state and style"""
    from openshock_autoflasher.styles import StateColors

    flasher.set_state("flashing")
    assert flasher.state == "flashing"
    assert flasher.current_style == StateColors.FLASHING


@patch("openshock_autoflasher.flasher.requests.get")
def test_fetch_version(mock_get, flasher):
    """Test version fetching with caching"""
    mock_response = Mock()
    mock_response.text = "1.0.0\n"
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    # First call should make request
    version = flasher.fetch_version()
    assert version == "1.0.0"
    assert mock_get.call_count == 1

    # Second call should use cache
    version = flasher.fetch_version()
    assert version == "1.0.0"
    assert mock_get.call_count == 1  # Still 1, not 2


@patch("openshock_autoflasher.flasher.requests.get")
def test_fetch_boards(mock_get, flasher):
    """Test boards fetching with caching"""
    mock_response = Mock()
    mock_response.text = "board1\nboard2\nboard3\n"
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    # First call should make request
    boards = flasher.fetch_boards("1.0.0")
    assert boards == ["board1", "board2", "board3"]
    assert mock_get.call_count == 1

    # Second call should use cache
    boards = flasher.fetch_boards("1.0.0")
    assert boards == ["board1", "board2", "board3"]
    assert mock_get.call_count == 1  # Still 1, not 2


@patch("openshock_autoflasher.flasher.requests.get")
def test_download_firmware(mock_get, flasher):
    """Test firmware download and verification"""
    import hashlib

    # Create test firmware data
    firmware_data = b"test firmware data"
    expected_hash = hashlib.sha256(firmware_data).hexdigest()

    # Mock responses
    def mock_get_side_effect(url, *args, **kwargs):
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        if "firmware.bin" in url and "hashes" not in url:
            mock_response.content = firmware_data
        elif "hashes.sha256.txt" in url:
            mock_response.text = f"{expected_hash}  firmware.bin\n"
        return mock_response

    mock_get.side_effect = mock_get_side_effect

    result = flasher.download_firmware("1.0.0", "test-board")
    assert result == firmware_data


@patch("openshock_autoflasher.flasher.requests.get")
def test_download_firmware_hash_mismatch(mock_get, flasher):
    """Test firmware download fails on hash mismatch"""
    firmware_data = b"test firmware data"
    wrong_hash = "0" * 64  # Invalid hash

    def mock_get_side_effect(url, *args, **kwargs):
        mock_response = Mock()
        mock_response.raise_for_status = Mock()
        if "firmware.bin" in url and "hashes" not in url:
            mock_response.content = firmware_data
        elif "hashes.sha256.txt" in url:
            mock_response.text = f"{wrong_hash}  firmware.bin\n"
        return mock_response

    mock_get.side_effect = mock_get_side_effect

    with pytest.raises(ValueError, match="Hash mismatch"):
        flasher.download_firmware("1.0.0", "test-board")


@patch("openshock_autoflasher.flasher.serial.tools.list_ports.comports")
def test_detect_new_port(mock_comports, flasher):
    """Test new port detection"""
    # Initial state - no ports
    mock_comports.return_value = []
    flasher.known_ports = set()

    # No new ports
    new_ports = flasher.detect_new_port()
    assert new_ports is None

    # Add a new port
    mock_port = Mock()
    mock_port.device = "/dev/ttyUSB0"
    mock_comports.return_value = [mock_port]

    new_ports = flasher.detect_new_port()
    assert new_ports == ["/dev/ttyUSB0"]
    assert "/dev/ttyUSB0" in flasher.known_ports

    # Same port again - should not be detected as new
    new_ports = flasher.detect_new_port()
    assert new_ports is None


def test_flasher_different_channels():
    """Test flasher initialization with different channels"""
    stable = AutoFlasher(channel="stable", board="test")
    assert stable.channel == "stable"

    beta = AutoFlasher(channel="beta", board="test")
    assert beta.channel == "beta"

    develop = AutoFlasher(channel="develop", board="test")
    assert develop.channel == "develop"


def test_flasher_erase_flash_option():
    """Test erase_flash option"""
    no_erase = AutoFlasher(channel="stable", board="test", erase_flash=False)
    assert no_erase.erase_flash is False

    with_erase = AutoFlasher(channel="stable", board="test", erase_flash=True)
    assert with_erase.erase_flash is True


def test_flasher_post_flash_commands():
    """Test post_flash_commands initialization"""
    # No commands
    no_commands = AutoFlasher(channel="stable", board="test")
    assert no_commands.post_flash_commands == []

    # With commands
    with_commands = AutoFlasher(
        channel="stable", board="test", post_flash_commands=["cmd1", "cmd2"]
    )
    assert with_commands.post_flash_commands == ["cmd1", "cmd2"]


@patch("openshock_autoflasher.flasher.serial.Serial")
@patch("openshock_autoflasher.flasher.time.sleep")
def test_execute_post_flash_commands(mock_sleep, mock_serial):
    """Test execution of post-flash commands over serial"""
    # Create flasher with commands
    flasher = AutoFlasher(
        channel="stable",
        board="test",
        post_flash_commands=["cmd1", "cmd2", "cmd3"],
    )

    # Mock serial connection
    mock_ser_instance = MagicMock()
    mock_ser_instance.in_waiting = 0
    mock_serial.return_value = mock_ser_instance

    # Execute commands
    flasher.execute_post_flash_commands("/dev/ttyUSB0")

    # Verify serial was opened
    mock_serial.assert_called_once_with("/dev/ttyUSB0", 115200, timeout=2)

    # Verify commands were sent
    assert mock_ser_instance.write.call_count == 3
    mock_ser_instance.write.assert_any_call(b"cmd1\n")
    mock_ser_instance.write.assert_any_call(b"cmd2\n")
    mock_ser_instance.write.assert_any_call(b"cmd3\n")

    # Verify serial was closed
    mock_ser_instance.close.assert_called_once()
