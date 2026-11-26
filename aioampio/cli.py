"""Validate Ampio configuration or run a receive-only bridge monitor."""

from __future__ import annotations

import argparse
import asyncio
import logging
from pathlib import Path

import yaml

from .bridge import AmpioBridge
from .config import Config

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
    ap.add_argument(
        "--interface",
        default="waveshare",
        type=str.lower,
        help="python-can backend (default: waveshare)",
    )
    ap.add_argument("--channel", default="can0", help="CAN channel (default: can0)")
    ap.add_argument("--host", help="Network gateway host (required for waveshare)")
    ap.add_argument(
        "--port", type=int, help="Network gateway port (waveshare default: 20001)"
    )
    ap.add_argument(
        "--validate", action="store_true", help="Validate configuration and exit"
    )
    args = ap.parse_args(argv)
    if not args.validate and args.interface == "waveshare" and not args.host:
        ap.error("--host is required for the waveshare interface")
    if args.port is not None and not 1 <= args.port <= 65535:
        ap.error("--port must be between 1 and 65535")

    async def runner() -> None:
        conf = await read_text(args.config)
        cfg = yaml.safe_load(conf)

        if args.validate:
            Config.model_validate(cfg)
            return

        bus_kwargs = {}
        if args.host is not None:
            bus_kwargs["host"] = args.host
        if args.port is not None:
            bus_kwargs["port"] = args.port
        elif args.interface == "waveshare":
            bus_kwargs["port"] = 20001
        bridge = AmpioBridge(
            cfg, interface=args.interface, channel=args.channel, **bus_kwargs
        )
        try:
            await bridge.initialize()
            await bridge.start()
            await asyncio.Event().wait()
        finally:
            await bridge.stop()

    try:
        asyncio.run(runner())
    except KeyboardInterrupt:
        pass
    except (OSError, yaml.YAMLError, ValueError) as exc:
        ap.error(str(exc))


if __name__ == "__main__":
    main()
