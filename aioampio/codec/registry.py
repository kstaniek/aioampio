"""Registry for CAN frame codecs."""

from __future__ import annotations
from importlib import import_module

from caneth import CANFrame

from .base import Codec, AmpioMessage
import asyncio


class CodecRegistry:
    def __init__(self) -> None:
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
        async def async_import(mod: str) -> None:
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
