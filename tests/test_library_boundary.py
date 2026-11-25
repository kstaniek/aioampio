"""Enforce that protocol code runs without any Home Assistant imports."""

from pathlib import Path
import subprocess
import sys

import aioampio


def test_library_initializes_without_homeassistant() -> None:
    """Block HA imports in a fresh interpreter and load all protocol resources."""
    root = str(Path(aioampio.__file__).resolve().parent.parent)
    script = f"""
import asyncio
import importlib.abc
import sys
sys.path.insert(0, {root!r})
class RejectHA(importlib.abc.MetaPathFinder):
    def find_spec(self, fullname, path=None, target=None):
        if fullname == "homeassistant" or fullname.startswith("homeassistant."):
            raise AssertionError("aioampio must not import Home Assistant")
sys.meta_path.insert(0, RejectHA())
from aioampio import AmpioBridge
async def run():
    bridge = AmpioBridge({{"devices": [{{"can_id": 291, "name": "Test", "model": 4, "lights": [{{"id": "light1", "name": "Test light", "states": ["aout.1"]}}]}}]}}, interface="virtual", channel="isolated")
    await bridge.initialize()
    assert bridge.lights["00000123_light1"].name == "Test light"
    await bridge.stop()
asyncio.run(run())
"""
    subprocess.run(
        [sys.executable, "-I", "-c", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )  # noqa: S603
