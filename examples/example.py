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
                for i in range(1, 17):
                    eid = f"00001e5d_light{i}"
                    # await bridge.lights.set_state(eid, brightness=255)
                    await bridge.lights.set_state(eid, on=True)
                    eid = f"000019c7_light{i}"
                # await bridge.lights.set_state("000019c7_light8", brightness=255)
                # RGBW
                await bridge.lights.set_state("00001879_light1", on=True)
                # await bridge.lights.set_state("00001879_light1", color=(255, 0, 0, 0))

                await bridge.lights.set_state("000019c7_light8", on=True)
                await bridge.lights.set_state("00001a1e_light1", on=True)
                await bridge.lights.set_state("00001885_light3", on=True)
                await asyncio.sleep(1)
                for i in range(1, 17):
                    eid = f"00001e5d_light{i}"
                    # await bridge.lights.set_state(eid, brightness=0)
                    await bridge.lights.set_state(eid, on=False)
                # await bridge.lights.set_state("000019c7_light8", brightness=0)
                # RGBW
                await bridge.lights.set_state("00001879_light1", on=False)
                # await bridge.lights.set_state("00001879_light1", color=(0, 0, 0, 0))

                await bridge.lights.set_state("000019c7_light8", on=False)
                await bridge.lights.set_state("00001a1e_light1", on=False)
                await bridge.lights.set_state("00001885_light3", on=False)
                await asyncio.sleep(1)
            # await stop_event.wait()
        except KeyboardInterrupt:
            pass
        finally:
            await bridge.stop()

    asyncio.run(runner())


if __name__ == "__main__":
    main()
