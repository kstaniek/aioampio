"""Registry for frame decoders."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol, runtime_checkable, Any, Final
import logging

from .base import CANFrame

log = logging.getLogger(__name__)


@runtime_checkable
class FrameDecoder(Protocol):
    """Minimal contract every decoder already satisfies."""

    def decode(self, frame: CANFrame) -> Iterable[Any] | None:
        """Decode a frame into zero or more objects."""


@runtime_checkable
class SupportsMatches(Protocol):
    """Optional fast pre-filter."""

    def matches(self, frame: CANFrame) -> bool:
        """Return True if this decoder wants to decode the given frame."""


class CodecRegistry:
    """Holds decoders and fans frames out to matching ones."""

    __slots__ = ("_decoders", "_log_errors")

    def __init__(self) -> None:
        """Create empty registry."""
        self._decoders: list[FrameDecoder] = []
        self._log_errors: bool = True

    # --- registration ------------------------------------------------------
    def register(self, decoder: FrameDecoder) -> FrameDecoder:
        """Register a decoder instance."""
        self._decoders.append(decoder)
        return decoder

    def clear(self) -> None:
        """Remove all registered decoders."""
        self._decoders.clear()

    # --- dispatch ----------------------------------------------------------
    def decode(self, frame: CANFrame) -> list[Any]:
        """Decode a frame by passing it to all matching registered decoders."""
        out: list[Any] = []
        for dec in list(self._decoders):
            try:
                # Optional cheap pre-filter
                if isinstance(dec, SupportsMatches) and not dec.matches(frame):
                    continue

                part = dec.decode(frame)
                if part:
                    # Normalize to list efficiently
                    if isinstance(part, list):
                        out.extend(part)
                    else:
                        out.extend(list(part))
            except Exception:  # pylint: disable=broad-except
                # keep other decoders alive
                if self._log_errors:
                    log.exception(
                        "Decoder %s failed on frame id=0x%X", dec, frame.can_id
                    )
        return out


# singleton – same import path you already use
_SINGLETON: Final[CodecRegistry] = CodecRegistry()


def registry() -> CodecRegistry:
    """Return the global singleton registry instance."""
    return _SINGLETON
