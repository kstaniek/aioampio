"""Example CLI command."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import yaml

from aioampio import AmpioBridge

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")


async def read_text(path: str) -> str:
    """Read text file asynchronously."""
    return await asyncio.to_thread(Path(path).read_text, encoding="utf-8")


def main(argv: list[str] | None = None) -> None:
    """Start for the CLI."""
    ap = argparse.ArgumentParser(
        prog="aioampio", description="Ampio Bridge Test Harness"
    )
    ap.add_argument("--config", required=True, help="Path to YAML configuration file")
    ap.add_argument("--host", required=True, help="Host to connect to")
    ap.add_argument("--port", type=int, default=20001, help="Port to connect to")
    ap.add_argument("--pin", required=True, help="PIN for arming/disarming")
    args = ap.parse_args(argv)

    async def runner() -> None:
        conf = await read_text(args.config)
        cfg = yaml.safe_load(conf)
        bridge = AmpioBridge(cfg, args.host, args.port)

        await bridge.initialize()
        await bridge.start()
        # stop_event = asyncio.Event()
        try:
            while True:
                await bridge.alarm_control_panels.arm_in_mode0(
                    "00001ecc_zone3", code=args.pin
                )
                await asyncio.sleep(10)
                await bridge.alarm_control_panels.disarm(
                    "00001ecc_zone3", code=args.pin
                )
                await asyncio.sleep(10)
            # await stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            await bridge.stop()

    asyncio.run(runner())


if __name__ == "__main__":
    main()
