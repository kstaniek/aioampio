"""Utility functions for the Ampio integration."""

import asyncio
from pathlib import Path

# Import from centralized types module
# pylint: disable=unused-import
from aioampio.types import CanInterface  # noqa: F401 - re-exported for backward compatibility


async def read_text(path: str) -> str:
    """Read text file asynchronously."""
    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")


# ---- CAN interface discovery ---------------------------------------


def _discover_backends() -> set[str]:
    """Try to discover available python-can backends at runtime."""
    names: set[str] = set()
    try:
        # python-can exposes backends via can.interface module
        from can import interface as _can_iface  # pylint: disable=import-outside-toplevel

        backends = getattr(_can_iface, "BACKENDS", None)
        if isinstance(backends, dict):
            names.update(map(str, backends.keys()))
    except Exception:  # pylint: disable=broad-except
        pass

    # Always include your supported set (incl. custom 'waveshare')
    names.update(
        [
            "waveshare",
            "cannelloni",
        ]
    )
    # Normalize
    return {n.lower() for n in names if isinstance(n, str) and n}
