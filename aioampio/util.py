"""Utility functions for the Ampio integration."""

import asyncio
from pathlib import Path
from typing import Literal, TypeAlias


async def read_text(path: str) -> str:
    """Read text file asynchronously."""
    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")


# ---- CAN interface typing & discovery ---------------------------------------
# Common python-can backend names + your custom 'waveshare'
KnownCanInterface = Literal[
    "waveshare",
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

CanInterface: TypeAlias = KnownCanInterface  # extend if you adopt more backends


def _discover_backends() -> set[str]:
    """Try to discover available python-can backends at runtime."""
    names: set[str] = set()
    try:
        # python-can exposes backends via can.interface module
        from can import interface as _can_iface  # pylint: disable=import-outside-toplevel

        # Newer python-can:
        discovered = getattr(_can_iface, "VALID_INTERFACES", None)
        if discovered:
            names.update(map(str, discovered))
        # Older python-can:
        backends = getattr(_can_iface, "BACKENDS", None)
        if isinstance(backends, dict):
            names.update(map(str, backends.keys()))
    except Exception:  # pylint: disable=broad-except
        pass

    # Always include your supported set (incl. custom 'waveshare')
    names.update(
        [
            "waveshare",
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
    )
    # Normalize
    return {n.lower() for n in names if isinstance(n, str) and n}
