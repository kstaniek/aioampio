"""Registry for CAN frame codecs."""

from __future__ import annotations

import asyncio
from importlib import import_module

from .base import Codec, AmpioMessage, CANFrame


class CodecRegistry:
    """Registry for CAN frame codecs."""

    def __init__(self) -> None:
        """Initialize the codec registry."""
        self._codecs: list[Codec] = []

    def register(self, codec: Codec) -> None:
        """Register a codec."""
        self._codecs.append(codec)

    def decode(self, frame: CANFrame) -> list[AmpioMessage] | None:
        """Decode a CAN frame into an Ampio message."""
        for codec in self._codecs:
            message = codec.decode(frame)
            if message:
                return message
        return None

    async def load_modules(self, modules: list[str]) -> None:
        """Dynamically load codec modules."""

        async def async_import(mod: str) -> None:
            """Import a module asynchronously."""
            loop = asyncio.get_running_loop()
            await loop.run_in_executor(None, import_module, mod)

        await asyncio.gather(*(async_import(mod) for mod in modules))


_registry = CodecRegistry()


def register_codec(codec: Codec) -> None:
    """Register a codec globally."""
    _registry.register(codec)


def registry() -> CodecRegistry:
    """Get the global codec registry."""
    return _registry
