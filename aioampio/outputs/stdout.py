"""Standard Output."""

from __future__ import annotations

import datetime as dt

from caneth import CANFrame

from aioampio.codec.base import AmpioMessage


class StdoutOutput:
    def __init__(self, fmt: str | None = None) -> None:
        self.fmt = fmt or "{timestamp} {dir} id=0x{id:08X} dlc={dlc} data={data_hex}"

    def emit_raw(self, frame: CANFrame) -> None:
        ts = dt.datetime.now().isoformat(timespec="seconds")  # noqa: DTZ005
        line = self.fmt.format(
            timestamp=ts,
            dir="RX",
            id=frame.can_id,
            dlc=frame.dlc,
            data_hex=frame.data[: frame.dlc].hex(),
            topic="",
            payload="",
        )
        print(line)  # noqa: T201

    def emit_msg(self, msg: AmpioMessage) -> None:
        ts = dt.datetime.now().isoformat(timespec="seconds")  # noqa: DTZ005
        frame = msg.raw
        line = self.fmt.format(
            timestamp=ts,
            dir="RX",
            id=frame.can_id,
            dlc=frame.dlc,
            data_hex=frame.data[: frame.dlc].hex(),
            topic=msg.topic,
            payload=msg.payload,
        )
        print(line)  # noqa: T201
