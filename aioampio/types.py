"""Shared type definitions for the aioampio package.

This module contains common type aliases and protocols used across
multiple modules in the aioampio package. Centralizing these definitions
helps avoid circular imports and provides a single source of truth for
type information.

Types:
    CanInterface: Type alias for CAN interface backend names
    BusKwargs: Type alias for python-can Bus constructor arguments
"""

from typing import Any, Literal, Protocol


# CAN Interface Types
# Common python-can backend names + custom backends
# Type alias for supported CAN interface backend names.
# This defines the known python-can interface backends that can be
# used with the Ampio bridge. The actual availability depends on the
# installed python-can plugins.
CanInterface = Literal[
    "waveshare",
    "cannelloni",
    "socketcand",
    "socketcan",
    "slcan",
    "pcan",
    "kvaser",
    "ixxat",
    "vector",
    "nican",
    "neovi",
    "usb2can",
    "cantact",  # codespell:ignore
    "canalystii",
    "seeedstudio",
    "virtual",
]

# Type alias for python-can Bus constructor keyword arguments.
# These are interface-specific configuration options that vary by CAN backend.
# Examples include bitrate, data_bitrate, fd, etc.
BusKwargs = dict[str, Any]


class LoggerProtocol(Protocol):
    """Protocol defining the minimum logging interface required by bridge components.

    This protocol allows for duck-typing of logger objects, enabling the use
    of standard library logging.Logger or compatible implementations.
    """

    def debug(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a debug message."""

    def info(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an info message."""

    def warning(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a warning message."""

    def error(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an error message."""

    def critical(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log a critical message."""

    def exception(self, msg: str, *args: Any, **kwargs: Any) -> None:
        """Log an exception with traceback."""
