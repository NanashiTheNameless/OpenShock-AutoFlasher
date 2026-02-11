"""
Tests for styles module
"""

from openshock_autoflasher.styles import StateColors, console
from rich.style import Style
from rich.console import Console, ColorSystem


def test_state_colors_defined():
    """Test that all state colors are defined"""
    assert isinstance(StateColors.WAITING, Style)
    assert isinstance(StateColors.FLASHING, Style)
    assert isinstance(StateColors.DONE, Style)
    assert isinstance(StateColors.ERROR, Style)


def test_state_colors_have_backgrounds():
    """Test that state colors have background colors"""
    assert StateColors.WAITING.bgcolor is not None
    assert StateColors.FLASHING.bgcolor is not None
    assert StateColors.DONE.bgcolor is not None
    assert StateColors.ERROR.bgcolor is not None


def test_console_instance():
    """Test that console is properly initialized"""
    assert isinstance(console, Console)
    assert console._force_terminal is True
    assert console._color_system == ColorSystem.TRUECOLOR
