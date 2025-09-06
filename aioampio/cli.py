"""Example CLI command."""

from __future__ import annotations

import argparse
import asyncio
import logging

from .bridge import AmpioBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(
        prog="aioampio", description="Ampio Bridge Test Harness"
    )
    ap.add_argument("--config", required=True, help="Path to YAML configuration file")
    ap.add_argument("--host", required=True, help="Host to connect to")
    ap.add_argument("--port", type=int, default=20001, help="Port to connect to")
    args = ap.parse_args(argv)

    bridge = AmpioBridge(args.config, args.host, args.port)

    async def runner() -> None:
        await bridge.initialize()
        await bridge.start()
        stop_event = asyncio.Event()
        try:
            await stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            await bridge.stop()

    asyncio.run(runner())
