"""Utility functions for the Ampio integration."""

import asyncio
from pathlib import Path


async def read_text(path: str) -> str:
    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")
