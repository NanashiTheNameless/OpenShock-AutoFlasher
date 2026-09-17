"""
Tests for flasher module
"""

import pytest
from esptool.util import FatalError
from unittest.mock import Mock, patch, MagicMock

from openshock_autoflasher.constants import BAUD_RATE
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
    assert flasher.post_flash_delay == 0.0
    assert flasher.state == "waiting"
    assert flasher.version_cache is None
    assert flasher.boards_cache is None


@pytest.mark.parametrize("installed", [True, False])
def test_run_handles_missing_package_metadata(flasher, installed):
    from importlib.metadata import PackageNotFoundError

    flasher.test_only = True
    with (
        patch(
            "openshock_autoflasher.flasher.importlib.metadata.version",
            return_value="0.4.0",
            side_effect=None if installed else PackageNotFoundError("OpenShock-AutoFlasher"),
        ),
        patch.object(flasher, "detect_new_port", side_effect=KeyboardInterrupt()),
        patch.object(flasher, "log") as log,
    ):
        flasher.run()
    version = "0.4.0" if installed else "unknown (not installed)"
    log.assert_any_call(f"OpenShock Auto-Flasher {version}")


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


def test_flasher_post_flash_delay():
    """Test post_flash_delay initialization"""
    flasher = AutoFlasher(channel="stable", board="test", post_flash_delay=1250)
    assert flasher.post_flash_delay == 1250


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
    mock_serial.assert_called_once_with("/dev/ttyUSB0", 115200, timeout=0.2)

    # Verify commands were sent
    assert mock_ser_instance.write.call_count == 3
    mock_ser_instance.write.assert_any_call(b"cmd1\n")
    mock_ser_instance.write.assert_any_call(b"cmd2\n")
    mock_ser_instance.write.assert_any_call(b"cmd3\n")

    # Verify serial was closed
    mock_ser_instance.close.assert_called_once()


@patch("openshock_autoflasher.flasher.serial.Serial")
@patch("openshock_autoflasher.flasher.time.sleep")
def test_execute_post_flash_commands_waits_between_commands(mock_sleep, mock_serial):
    """Test post-flash delay in milliseconds is applied between commands only."""
    flasher = AutoFlasher(
        channel="stable",
        board="test",
        post_flash_commands=["cmd1", "cmd2", "cmd3"],
        post_flash_delay=1500,
    )

    mock_ser_instance = MagicMock()
    mock_serial.return_value = mock_ser_instance

    flasher.execute_post_flash_commands("/dev/ttyUSB0")

    assert mock_sleep.call_args_list == [
        ((2,),),
        ((0.5,),),
        ((1.5,),),
        ((1.5,),),
    ]


def test_flasher_initialization_with_version():
    """Test AutoFlasher initialization with version parameter"""
    flasher = AutoFlasher(
        channel="stable",
        board="test-board",
        version="2.7.0",
    )
    assert flasher.version == "2.7.0"
    assert flasher.channel == "stable"
    assert flasher.board == "test-board"


def test_flasher_version_is_optional():
    """Test that version parameter is optional"""
    flasher = AutoFlasher(
        channel="stable",
        board="test-board",
    )
    assert flasher.version is None


@patch("openshock_autoflasher.flasher.requests.get")
def test_fetch_version_with_specified_version(mock_get, flasher):
    """Test that fetch_version returns specified version without network call"""
    flasher_with_version = AutoFlasher(
        channel="stable",
        board="test-board",
        version="2.7.0",
    )

    version = flasher_with_version.fetch_version()
    assert version == "2.7.0"
    # Verify no network request was made
    mock_get.assert_not_called()


@patch("openshock_autoflasher.flasher.requests.get")
def test_fetch_version_without_specified_version(mock_get, flasher):
    """Test that fetch_version makes network call when version not specified"""
    mock_response = Mock()
    mock_response.text = "1.5.0\n"
    mock_response.raise_for_status = Mock()
    mock_get.return_value = mock_response

    version = flasher.fetch_version()
    assert version == "1.5.0"
    # Verify network request was made
    mock_get.assert_called_once()


def test_flasher_with_version_and_all_options():
    """Test AutoFlasher with version and other options"""
    flasher = AutoFlasher(
        channel="beta",
        board="esp32-s3",
        version="2.7.0",
        erase_flash=True,
        auto_flash=False,
        post_flash_commands=["help", "version"],
        post_flash_delay=750,
        alert=True,
    )

    assert flasher.version == "2.7.0"
    assert flasher.channel == "beta"
    assert flasher.board == "esp32-s3"
    assert flasher.erase_flash is True
    assert flasher.auto_flash is False
    assert flasher.post_flash_commands == ["help", "version"]
    assert flasher.post_flash_delay == 750
    assert flasher.alert is True


def test_flasher_defaults_chip_to_auto():
    """Test AutoFlasher defaults to esptool autodetection."""
    flasher = AutoFlasher(channel="stable", board="test-board")

    assert flasher.chip == "auto"


def test_flasher_with_explicit_chip():
    """Test AutoFlasher stores explicit chip overrides."""
    flasher = AutoFlasher(channel="stable", board="test-board", chip="ESP32S3")

    assert flasher.chip == "esp32s3"


def test_flasher_rejects_unsupported_chip():
    """Test unsupported esptool chip values fail early."""
    with pytest.raises(ValueError, match="Unsupported chip"):
        AutoFlasher(channel="stable", board="test-board", chip="invalid")


def test_flash_device_uses_default_auto_chip_for_erase_and_flash(flasher):
    """Test erase and write commands both receive the default auto chip."""
    flasher.erase_flash = True

    with (
        patch.object(flasher, "download_firmware", return_value=b"firmware"),
        patch.object(flasher, "_run_esptool") as mock_run_esptool,
    ):
        flasher.flash_device("/dev/ttyUSB0", "1.0.0", "Seeed-Xiao-ESP32C3")

    assert mock_run_esptool.call_count == 2
    erase_args = mock_run_esptool.call_args_list[0][0][0]
    write_args = mock_run_esptool.call_args_list[1][0][0]

    assert erase_args == [
        "--chip",
        "auto",
        "--port",
        "/dev/ttyUSB0",
        "--baud",
        BAUD_RATE,
        "erase-flash",
    ]
    assert write_args[:7] == [
        "--chip",
        "auto",
        "--port",
        "/dev/ttyUSB0",
        "--baud",
        BAUD_RATE,
        "write-flash",
    ]


@patch("openshock_autoflasher.flasher.time.sleep")
@patch("openshock_autoflasher.flasher.esptool.main")
def test_run_esptool_retries_on_stopiteration(mock_esptool_main, mock_sleep, flasher):
    """Test transient StopIteration gets retried and succeeds."""
    mock_esptool_main.side_effect = [StopIteration(), None]

    flasher._run_esptool(["erase-flash"], "Erase")

    assert mock_esptool_main.call_count == 2
    mock_sleep.assert_called_once_with(1)


@patch("openshock_autoflasher.flasher.esptool.main")
def test_run_esptool_raises_on_repeated_stopiteration(mock_esptool_main, flasher):
    """Test repeated StopIteration raises a clear operation error."""
    mock_esptool_main.side_effect = [StopIteration(), StopIteration()]

    with pytest.raises(Exception, match="Erase failed after retry"):
        flasher._run_esptool(["erase-flash"], "Erase")


@pytest.mark.parametrize("command,operation", [("erase-flash", "Erase"), ("write-flash", "Flash")])
def test_stub_start_failure_reconnects_at_lower_initial_baud(flasher, command, operation):
    args = ["--chip", "auto", "--port", "/dev/ttyUSB1", "--baud", "460800", command]
    original = args.copy()
    with (
        patch("openshock_autoflasher.flasher.esptool.main") as run,
        patch("openshock_autoflasher.flasher.time.sleep"),
        patch.object(flasher, "log") as log,
    ):
        run.side_effect = [FatalError("Failed to start stub flasher. There was no response."), None]
        flasher._run_esptool(args, operation)
    assert run.call_count == 2
    assert run.call_args_list[0].args[0] == original
    expected = original.copy()
    expected[expected.index("--baud") + 1] = "57600"
    assert run.call_args_list[1].args[0] == expected
    assert args == original
    assert any("reconnecting at 57600 baud" in call.args[0] for call in log.call_args_list)


def test_stub_start_retries_are_bounded_and_failure_is_preserved(flasher):
    with (
        patch("openshock_autoflasher.flasher.esptool.main") as run,
        patch("openshock_autoflasher.flasher.time.sleep"),
    ):
        run.side_effect = FatalError("Failed to start stub flasher. There was no response.")
        with pytest.raises(Exception, match="Erase failed: Failed to start stub flasher") as error:
            flasher._run_esptool(["erase-flash"], "Erase", retries=2)
    assert [call.args[0] for call in run.call_args_list] == [
        ["erase-flash"],
        ["--baud", "57600", "erase-flash"],
        ["--baud", "9600", "erase-flash"],
    ]
    assert "power-cycle the hub" in str(error.value)


def test_unrelated_fatal_errors_do_not_trigger_stub_recovery(flasher):
    with patch("openshock_autoflasher.flasher.esptool.main") as run:
        run.side_effect = FatalError("Wrong chip argument")
        with pytest.raises(Exception, match="Erase failed: Wrong chip argument"):
            flasher._run_esptool(["erase-flash"], "Erase", retries=2)
    run.assert_called_once()


def test_monitor_is_never_flashed_or_erased(tmp_path):
    from openshock_autoflasher.hardware_tests import HardwareTestConfig, HardwareTestError

    port = tmp_path / "ttyUSB0"
    port.touch()
    alias = tmp_path / "monitor"
    alias.symlink_to(port)
    flasher = AutoFlasher(
        board="board", erase_flash=True, hardware_tests=HardwareTestConfig(rf_port=str(alias))
    )
    with patch.object(flasher, "download_firmware") as download:
        with pytest.raises(HardwareTestError, match="Refusing"):
            flasher.flash_device(str(port), "1.0", "board")
    download.assert_not_called()
    assert flasher.state == "error"


def test_reconnected_monitor_is_excluded_from_detection():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_port="monitor"))
    with patch("openshock_autoflasher.flasher.serial.tools.list_ports.comports") as ports:
        ports.return_value = [Mock(device="monitor"), Mock(device="dut")]
        assert flasher.detect_new_port() == ["dut"]
        assert flasher.detect_new_port() is None
        ports.return_value = []
        assert flasher.detect_new_port() is None
        ports.return_value = [Mock(device="monitor")]
        assert flasher.detect_new_port() is None


def test_hardware_tests_gate_flash_success_and_alert(flasher):
    from openshock_autoflasher.hardware_tests import HardwareTestConfig, HardwareTestError

    flasher.hardware_tests = HardwareTestConfig(rf_port="monitor")
    flasher.alert = True
    with (
        patch.object(flasher, "download_firmware", return_value=b"firmware"),
        patch.object(flasher, "_run_esptool"),
        patch.object(flasher, "test_device", side_effect=HardwareTestError("RF failed")) as check,
        patch.object(flasher, "play_alert") as alert,
    ):
        with pytest.raises(HardwareTestError, match="RF failed"):
            flasher.flash_device("dut", "1.0", "board")
    check.assert_called_once_with("dut")
    alert.assert_not_called()
    assert flasher.state == "error"


def test_setup_failure_sets_error_state(flasher):
    from openshock_autoflasher.hardware_tests import HardwareTestConfig, HardwareTestError

    flasher.hardware_tests = HardwareTestConfig(rf_port="monitor")
    with patch(
        "openshock_autoflasher.flasher.run_hardware_tests",
        side_effect=HardwareTestError("No serial"),
    ):
        with pytest.raises(HardwareTestError, match="setup: No serial"):
            flasher.test_device("dut")
    assert flasher.state == "error"


def test_auto_rf_reserves_first_plugged_device_before_detecting_hubs():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    monitor = Mock(device="monitor", serial_number="tester-1", vid=1, pid=2)
    hub = Mock(device="hub", serial_number="hub-1", vid=1, pid=2)
    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with (
        patch(
            "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
            side_effect=[[], [], [monitor], [monitor, hub]],
        ),
        patch("openshock_autoflasher.flasher.time.sleep"),
    ):
        flasher.prepare_rf_monitor()
        assert flasher.hardware_tests.rf_port == "monitor"
        assert flasher.known_ports == {"monitor"}
        assert flasher.detect_new_port() == ["hub"]


def test_auto_rf_accepts_only_existing_tester_and_excludes_explicit_target():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    monitor = Mock(device="monitor", serial_number=None)
    hub = Mock(device="hub")
    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with patch(
        "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
        return_value=[monitor, hub],
    ):
        flasher.prepare_rf_monitor(target_port="hub")
    assert flasher.hardware_tests.rf_port == "monitor"
    assert flasher.rf_monitor_identity is None


def test_auto_rf_requires_replug_when_existing_ports_are_ambiguous():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    monitor = Mock(device="monitor", serial_number=None)
    other = Mock(device="other")
    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with (
        patch(
            "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
            side_effect=[[monitor, other], [other], [other, monitor]],
        ),
        patch("openshock_autoflasher.flasher.time.sleep"),
        patch.object(flasher, "log") as log,
    ):
        flasher.prepare_rf_monitor()
    assert flasher.hardware_tests.rf_port == "monitor"
    assert any("Multiple serial ports" in call.args[0] for call in log.call_args_list)


def test_auto_rf_does_not_choose_arbitrarily_when_two_ports_arrive_together():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    monitor = Mock(device="monitor", serial_number=None)
    other = Mock(device="other")
    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with (
        patch(
            "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
            side_effect=[[], [monitor, other], [other], [other, monitor]],
        ),
        patch("openshock_autoflasher.flasher.time.sleep"),
    ):
        flasher.prepare_rf_monitor()
    assert flasher.hardware_tests.rf_port == "monitor"


def test_auto_rf_tracks_tester_serial_number_after_port_changes():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    original = Mock(device="monitor-old", serial_number="tester", vid=1, pid=2)
    reconnected = Mock(device="monitor-new", serial_number="tester", vid=1, pid=2)
    hub = Mock(device="hub", serial_number="hub", vid=1, pid=2)
    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with patch(
        "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
        side_effect=[[original], [], [reconnected, hub]],
    ):
        flasher.prepare_rf_monitor()
        assert flasher.detect_new_port() is None
        assert flasher.detect_new_port() == ["hub"]
    assert flasher.hardware_tests.rf_port == "monitor-new"
    assert flasher.is_monitor_port("monitor-new")


def test_ambiguous_tester_identity_is_never_returned_for_flashing():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    original = Mock(device="monitor-old", serial_number="tester", vid=1, pid=2)
    copies = [Mock(device=f"monitor-{i}", serial_number="tester", vid=1, pid=2) for i in range(2)]
    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with patch(
        "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
        side_effect=[[original], copies],
    ):
        flasher.prepare_rf_monitor()
        assert flasher.detect_new_port() is None


def test_manual_rf_port_does_not_wait_for_auto_detection():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_port="monitor"))
    with patch("openshock_autoflasher.flasher.serial.tools.list_ports.comports") as ports:
        flasher.prepare_rf_monitor()
    ports.assert_not_called()


def test_unresolved_auto_rf_cannot_flash_a_device():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig, HardwareTestError

    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with patch.object(flasher, "download_firmware") as download:
        with pytest.raises(HardwareTestError, match="Select the RF tester"):
            flasher.flash_device("monitor", "1.0", "board")
    download.assert_not_called()


def test_auto_rf_startup_shows_enabled_while_awaiting_tester():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    flasher = AutoFlasher(hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with patch.object(flasher, "log") as log:
        flasher.log_test_settings()
    log.assert_any_call("RF test: True")
    log.assert_any_call("RF monitor port: auto-detect (plug tester in first)")


def test_continuous_auto_rf_flashes_only_hub_connected_after_tester():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    monitor = Mock(device="monitor", serial_number="tester", vid=1, pid=2)
    hub = Mock(device="hub", serial_number="hub", vid=1, pid=2)
    flasher = AutoFlasher(board="board", hardware_tests=HardwareTestConfig(rf_auto_detect=True))
    with (
        patch("openshock_autoflasher.flasher.importlib.metadata.version", return_value="0.4.0"),
        patch(
            "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
            side_effect=[[], [monitor], [monitor, hub], KeyboardInterrupt()],
        ),
        patch("openshock_autoflasher.flasher.time.sleep"),
        patch.object(flasher, "fetch_version", return_value="1.0"),
        patch.object(flasher, "fetch_boards", return_value=["board"]),
        patch.object(flasher, "flash_device") as flash,
    ):
        flasher.run()
    flash.assert_called_once_with("hub", "1.0", "board")
    assert flasher.hardware_tests.rf_port == "monitor"


@pytest.mark.parametrize("auto_tester", [False, True])
def test_continuous_test_only_detects_hubs_and_continues_after_failure(auto_tester):
    from unittest.mock import call
    from openshock_autoflasher.hardware_tests import HardwareTestConfig, HardwareTestError

    monitor = Mock(device="monitor", serial_number="tester", vid=1, pid=2)
    first = Mock(device="hub-one", serial_number="hub-one", vid=1, pid=2)
    second = Mock(device="hub-two", serial_number="hub-two", vid=1, pid=2)
    # The explicit tester is already connected; automatic selection sees it arrive first.
    ports = ([[], [monitor]] if auto_tester else [[monitor]]) + [
        [monitor, first],
        [monitor],
        [monitor, second],
        KeyboardInterrupt(),
    ]
    flasher = AutoFlasher(
        board="board",
        test_only=True,
        erase_flash=True,
        post_flash_commands=["factoryreset"],
        hardware_tests=HardwareTestConfig(
            wifi=True,
            rf_auto_detect=auto_tester,
            rf_port=None if auto_tester else "monitor",
            factory_reset_after_test=True,
        ),
    )
    with (
        patch("openshock_autoflasher.flasher.serial.tools.list_ports.comports", side_effect=ports),
        patch("openshock_autoflasher.flasher.time.sleep"),
        patch.object(flasher, "fetch_version") as version,
        patch.object(flasher, "fetch_boards") as boards,
        patch.object(flasher, "download_firmware") as download,
        patch.object(flasher, "_run_esptool") as write,
        patch.object(flasher, "execute_post_flash_commands") as commands,
        patch.object(flasher, "flash_device") as flash,
        patch.object(
            flasher, "test_device", side_effect=[HardwareTestError("RF failed"), None]
        ) as test,
        patch.object(flasher, "log") as log,
    ):
        flasher.run()
    assert test.call_args_list == [call("hub-one"), call("hub-two")]
    for operation in (version, boards, download, write, commands, flash):
        operation.assert_not_called()
    log.assert_any_call("Test only: True")
    log.assert_any_call("Auto-flash: False")
    log.assert_any_call("Testing failed: RF failed")
    assert flasher.hardware_tests.factory_reset_after_test
    assert flasher.hardware_tests.rf_port == "monitor"


def test_continuous_wifi_only_detects_new_hub_without_tester():
    from openshock_autoflasher.hardware_tests import HardwareTestConfig

    existing = Mock(device="existing")
    hub = Mock(device="hub")
    flasher = AutoFlasher(
        board="board", test_only=True, hardware_tests=HardwareTestConfig(wifi=True)
    )
    with (
        patch(
            "openshock_autoflasher.flasher.serial.tools.list_ports.comports",
            side_effect=[[existing], [existing, hub], KeyboardInterrupt()],
        ),
        patch("openshock_autoflasher.flasher.time.sleep"),
        patch.object(flasher, "fetch_version") as version,
        patch.object(flasher, "flash_device") as flash,
        patch.object(flasher, "test_device") as test,
    ):
        flasher.run()
    test.assert_called_once_with("hub")
    version.assert_not_called()
    flash.assert_not_called()


@pytest.mark.parametrize("passed", [True, False])
def test_test_only_alert_requires_passing_tests(passed):
    from openshock_autoflasher.hardware_tests import (
        CheckResult,
        HardwareTestConfig,
        HardwareTestError,
        HardwareTestResult,
    )

    flasher = AutoFlasher(test_only=True, alert=True, hardware_tests=HardwareTestConfig(wifi=True))
    result = HardwareTestResult("hub", [CheckResult("wifi", passed, "AP check", 0)])
    with (
        patch("openshock_autoflasher.flasher.run_hardware_tests", return_value=result),
        patch.object(flasher, "play_alert") as alert,
    ):
        if passed:
            flasher.test_device("hub")
        else:
            with pytest.raises(HardwareTestError):
                flasher.test_device("hub")
    assert alert.call_count == int(passed)
