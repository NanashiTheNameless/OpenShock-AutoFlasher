"""
Tests for CLI module
"""

import pytest
from unittest.mock import Mock, patch

from openshock_autoflasher.cli import (
    fetch_boards_for_help,
    create_argument_parser,
)


@patch("openshock_autoflasher.cli.requests.get")
def test_fetch_boards_for_help_success(mock_get):
    """Test successful board fetching for help text"""
    # Mock version response
    mock_version_response = Mock()
    mock_version_response.text = "1.0.0"
    mock_version_response.raise_for_status = Mock()

    # Mock boards response
    mock_boards_response = Mock()
    mock_boards_response.text = "board1\nboard2\nboard3"
    mock_boards_response.raise_for_status = Mock()

    mock_get.side_effect = [mock_version_response, mock_boards_response]

    boards = fetch_boards_for_help("stable")
    assert boards == ["board1", "board2", "board3"]


@patch("openshock_autoflasher.cli.requests.get")
def test_fetch_boards_for_help_failure(mock_get):
    """Test board fetching handles network errors gracefully"""
    mock_get.side_effect = Exception("Network error")

    boards = fetch_boards_for_help("stable")
    assert "(Unable to fetch boards list - check network connection)" in boards


def test_create_argument_parser():
    """Test argument parser creation"""
    parser = create_argument_parser("stable")

    # Test default values
    args = parser.parse_args(["--board", "test-board"])
    assert args.channel == "stable"
    assert args.board == "test-board"
    assert args.erase is False
    assert args.no_auto is False
    assert args.post_flash is None


def test_argument_parser_all_options():
    """Test parser with all options"""
    parser = create_argument_parser("beta")

    args = parser.parse_args(
        ["--channel", "develop", "--board", "my-board", "--erase", "--no-auto"]
    )

    assert args.channel == "develop"
    assert args.board == "my-board"
    assert args.erase is True
    assert args.no_auto is True


def test_argument_parser_short_options():
    """Test parser with short option flags"""
    parser = create_argument_parser()

    args = parser.parse_args(["-C", "beta", "-B", "my-board", "-E", "-N"])

    assert args.channel == "beta"
    assert args.board == "my-board"
    assert args.erase is True
    assert args.no_auto is True


def test_argument_parser_requires_board():
    """Test that board argument is required"""
    parser = create_argument_parser()

    with pytest.raises(SystemExit):
        parser.parse_args([])


def test_argument_parser_channel_choices():
    """Test that only valid channels are accepted"""
    parser = create_argument_parser()

    # Valid channels
    for channel in ["stable", "beta", "develop"]:
        args = parser.parse_args(["--channel", channel, "--board", "test"])
        assert args.channel == channel

    # Invalid channel
    with pytest.raises(SystemExit):
        parser.parse_args(["--channel", "invalid", "--board", "test"])


def test_argument_parser_post_flash_single():
    """Test parser with single post-flash command"""
    parser = create_argument_parser()

    args = parser.parse_args(["--board", "test-board", "--post-flash", "command1"])

    assert args.post_flash == ["command1"]


def test_argument_parser_post_flash_multiple():
    """Test parser with multiple post-flash commands"""
    parser = create_argument_parser()

    args = parser.parse_args(
        [
            "--board",
            "test-board",
            "--post-flash",
            "command1",
            "--post-flash",
            "command2",
            "--post-flash",
            "command3",
        ]
    )

    assert args.post_flash == [
        "command1",
        "command2",
        "command3",
    ]


def test_argument_parser_post_flash_short_option():
    """Test parser with post-flash short option"""
    parser = create_argument_parser()

    args = parser.parse_args(["-B", "test-board", "-P", "command1", "-P", "command2"])

    assert args.post_flash == ["command1", "command2"]


def test_argument_parser_version_long_option():
    """Test parser with --version long option"""
    parser = create_argument_parser()

    args = parser.parse_args(["--board", "test-board", "--version", "2.7.0"])

    assert args.version == "2.7.0"
    assert args.board == "test-board"


def test_argument_parser_version_short_option():
    """Test parser with -V short option"""
    parser = create_argument_parser()

    args = parser.parse_args(["-B", "test-board", "-V", "2.8.1"])

    assert args.version == "2.8.1"
    assert args.board == "test-board"


def test_argument_parser_version_overrides_channel():
    """Test that --version overrides --channel selection"""
    parser = create_argument_parser()

    args = parser.parse_args(
        ["--board", "test-board", "--channel", "beta", "--version", "2.7.0"]
    )

    assert args.version == "2.7.0"
    assert args.channel == "beta"  # Channel is still set but version takes precedence


def test_argument_parser_version_is_optional():
    """Test that --version is optional"""
    parser = create_argument_parser()

    args = parser.parse_args(["--board", "test-board"])

    assert args.version is None
    assert args.board == "test-board"
