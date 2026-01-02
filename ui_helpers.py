"""
UI Helper utilities for terminal color output and formatting.
"""
from colorama import Fore, Style, init

# Initialize colorama for cross-platform support
init(autoreset=True)


class Colors:
    """Color constants for consistent terminal output."""
    SUCCESS = Fore.GREEN
    ERROR = Fore.RED
    WARNING = Fore.YELLOW
    INFO = Fore.CYAN
    HIGHLIGHT = Fore.MAGENTA
    DIM = Style.DIM
    BRIGHT = Style.BRIGHT
    RESET = Style.RESET_ALL


def color_text(text: str, color: str) -> str:
    """
    Wrap text with color codes.

    Args:
        text: Text to colorize
        color: Color constant from Colors class

    Returns:
        Colored text string
    """
    return f"{color}{text}{Style.RESET_ALL}"


def success(text: str) -> str:
    """Return green text for success messages."""
    return color_text(text, Colors.SUCCESS)


def error(text: str) -> str:
    """Return red text for error messages."""
    return color_text(text, Colors.ERROR)


def warning(text: str) -> str:
    """Return yellow text for warning messages."""
    return color_text(text, Colors.WARNING)


def info(text: str) -> str:
    """Return cyan text for informational messages."""
    return color_text(text, Colors.INFO)


def highlight(text: str) -> str:
    """Return magenta text for highlighted content."""
    return color_text(text, Colors.HIGHLIGHT)


def bright(text: str) -> str:
    """Return bright text."""
    return color_text(text, Colors.BRIGHT)


def format_currency(amount: float, colored: bool = True) -> str:
    """
    Format currency with color coding based on positive/negative value.

    Args:
        amount: Dollar amount to format
        colored: Whether to apply color coding

    Returns:
        Formatted currency string
    """
    formatted = f"${amount:,.2f}"

    if not colored:
        return formatted

    if amount > 0:
        return success(formatted)
    elif amount < 0:
        return error(formatted)
    else:
        return formatted


def format_percentage(value: float, colored: bool = True) -> str:
    """
    Format percentage with color coding based on positive/negative value.

    Args:
        value: Percentage value to format
        colored: Whether to apply color coding

    Returns:
        Formatted percentage string
    """
    formatted = f"{value:+.2f}%"

    if not colored:
        return formatted

    if value > 0:
        return success(formatted)
    elif value < 0:
        return error(formatted)
    else:
        return formatted


def format_side(side: str) -> str:
    """
    Format order side (BUY/SELL) with color coding.

    Args:
        side: Order side ('BUY' or 'SELL')

    Returns:
        Colored side string
    """
    if side.upper() == 'BUY':
        return success(side)
    elif side.upper() == 'SELL':
        return error(side)
    else:
        return side


def format_status(status: str) -> str:
    """
    Format order status with appropriate color.

    Args:
        status: Order status string

    Returns:
        Colored status string
    """
    status_upper = status.upper()

    if status_upper in ['FILLED', 'COMPLETED', 'SUCCESS']:
        return success(status)
    elif status_upper in ['CANCELLED', 'REJECTED', 'FAILED', 'EXPIRED']:
        return error(status)
    elif status_upper in ['PENDING', 'OPEN', 'ACTIVE']:
        return warning(status)
    else:
        return status


def print_header(text: str):
    """Print a formatted header."""
    print(f"\n{bright(text)}")
    print(bright("=" * len(text)))


def print_subheader(text: str):
    """Print a formatted subheader."""
    print(f"\n{info(text)}")
    print(info("-" * len(text)))


def print_success(text: str):
    """Print a success message."""
    print(success(f"✓ {text}"))


def print_error(text: str):
    """Print an error message."""
    print(error(f"✗ {text}"))


def print_warning(text: str):
    """Print a warning message."""
    print(warning(f"⚠ {text}"))


def print_info(text: str):
    """Print an informational message."""
    print(info(f"ℹ {text}"))
