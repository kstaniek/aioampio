"""Registry for CAN frame decoders"""

from __future__ import annotations

from typing import Iterable, Protocol
from .base import CANFrame


class Decoder(Protocol):
    """Protocol for CAN frame decoders."""

    def decode(self, frame: CANFrame) -> Iterable[object]:
        """Decode a CAN frame.

        Returns an iterable of decoded objects (can be empty if the codec does not match).
        """


class CodecRegistry:
    """Registry for CAN frame decoders."""

    def __init__(self) -> None:
        """Initialize the registry."""
        self._codecs: list[Decoder] = []

    def register(self, codec: Decoder) -> None:
        """Register a codec to the registry."""
        self._codecs.append(codec)

    def decode(self, frame: CANFrame) -> list[object]:
        """Try codecs in registration order and return the first non-empty result.

        Always returns a list (empty if no codec matched).
        """
        for codec in self._codecs:
            try:
                out = codec.decode(frame)
            except Exception:  # pylint: disable=broad-except
                # bad codec should not break the pipeline
                continue
            if not out:
                continue
            # If the codec returned an iterable, normalize to list
            return list(out)
        return []


# singleton access
_REGISTRY = CodecRegistry()


def registry() -> CodecRegistry:
    """Get the global codec registry instance."""
    return _REGISTRY
