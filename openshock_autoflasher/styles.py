"""
Terminal styling and colors for OpenShock Auto-Flasher
"""

from rich.console import Console
from rich.style import Style


# Color styles for different states
class StateColors:
    WAITING: Style = Style(bgcolor="blue", color="white", bold=True)
    FLASHING: Style = Style(bgcolor="yellow", color="black", bold=True)
    DONE: Style = Style(bgcolor="green", color="black", bold=True)
    ERROR: Style = Style(bgcolor="red", color="white", bold=True)


# Global console instance for rich output
console: Console = Console(force_terminal=True, color_system="truecolor")
