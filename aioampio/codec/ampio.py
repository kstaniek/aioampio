"""Ampio state frame codec and router (table-driven registration).

This module implements a single codec (`AmpioCodec`) that routes FE-based
Ampio state frames to typed, table-driven decoders using the DSL in
`spec.py`.  The result of decoding is a list of `AmpioMessage` objects.
"""

from __future__ import annotations

from collections.abc import Callable
from enum import Enum, unique
import logging
from types import MappingProxyType
from typing import Final

from .base import AmpioMessage, CANFrame
from .registry import registry
from .spec import (
    BitFlag,
    Const,
    EnumMasked,
    I8,
    Mask,
    Repeat,
    U16,
    U8,
    decode_payload,
)

# ---------------------------------------------------------------------
# Constants & types
# ---------------------------------------------------------------------

# Frame kind markers
_STATE_FLAG: Final = 0xFE  # General device broadcast
_STATE_SATEL_FLAG: Final = 0x10  # SATEL device broadcast
_MAX_SATEL_ZONES: Final = 8

# Dispatcher registry for FE-based state decoders
_state_decoders: dict["StateType", Callable[[CANFrame], list[AmpioMessage] | None]] = {}
_unknown_state_decoder: set[int] = set()


@unique
class StateType(Enum):
    """Ampio FE state frame subtypes (data[1])."""

    UNKNOWN_1 = 0x01
    TEMPERATURE_INT = 0x05
    TEMPERATURE = 0x06
    AOUT_1 = 0x0C
    AOUT_2 = 0x0D
    AOUT_3 = 0x0E
    BINOUT = 0x0F
    DATETIME = 0x10
    U32B = 0x18
    SATEL_ARMED = 0x19
    SATEL_ALARM = 0x1A
    BIN_1 = 0x1B
    BIN_2 = 0x1C
    BIN_3 = 0x1D
    BOUT_1 = 0x1E
    BOUT_2 = 0x1F
    BOUT_3 = 0x20
    EVENT = 0x2B
    S16B10000_1 = 0x21
    S16B10000_2 = 0x22
    S16B10000_3 = 0x23
    S16B10000_4 = 0x24
    S16B10000_5 = 0x25
    SATEL_BREACHED = 0x38
    SATEL_ARMING = 0x39
    SATEL_ARMING_10S = 0x3A
    S16B_1 = 0x44
    S16B_2 = 0x45
    S16B_3 = 0x46
    RGB = 0x49
    DIAGNOSTICS = 0x4F
    HEATING_ZONE_SUMMARY = 0xC8
    HEATING_ZONE_1 = 0xC9
    HEATING_ZONE_2 = 0xCA
    HEATING_ZONE_3 = 0xCB
    HEATING_ZONE_4 = 0xCC
    HEATING_ZONE_5 = 0xCD
    HEATING_ZONE_6 = 0xCE
    HEATING_ZONE_7 = 0xCF
    HEATING_ZONE_8 = 0xD0
    HEATING_ZONE_9 = 0xD1
    HEATING_ZONE_10 = 0xD2
    HEATING_ZONE_11 = 0xD3
    HEATING_ZONE_12 = 0xD4
    HEATING_ZONE_13 = 0xD5
    HEATING_ZONE_14 = 0xD6
    HEATING_ZONE_15 = 0xD7
    HEATING_ZONE_16 = 0xD8
    FLAG = 0x80


# SATEL response code → string
SATEL_RESPONSE_MAP = MappingProxyType(
    {
        0x00: "OK",
        0x01: "requesting user code not found",
        0x02: "no access",
        0x03: "selected user does not exist",
        0x04: "selected user already exists",
        0x05: "wrong code or code already exists",
        0x06: "telephone code already exists",
        0x07: "changed code is the same",
        0x08: "other error",
        0x11: "can not arm, but can use force arm",
        0x12: "can not arm",
        0xFF: "command accepted (will be processed)",
    }
)

# 3-bit heating mode encoded in bits 4..6 (mask 0x70) → label
_HEATING_MODE_MAP = MappingProxyType(
    {
        0: "mode0",
        1: "mode1",
        2: "mode2",
        3: "mode3",
        4: "mode4",
        5: "mode5",
        6: "mode6",
        7: "mode7",
    }
)

# ---------------------------------------------------------------------
# Helpers & registration
# ---------------------------------------------------------------------


def satel_response_to_str(value: int) -> str:
    """Return human-readable SATEL response name for `value`."""
    if value in SATEL_RESPONSE_MAP:
        return SATEL_RESPONSE_MAP[value]
    if 0x80 <= value <= 0x8F:
        return "other error"
    return "unknown"


def register_state_decoder(
    frame_type: StateType,
) -> Callable[
    [Callable[[CANFrame], list[AmpioMessage] | None]],
    Callable[[CANFrame], list[AmpioMessage] | None],
]:
    """Decorator to register a decoder for a given FE state `frame_type`."""

    def _decorator(
        fn: Callable[[CANFrame], list[AmpioMessage] | None],  # pylint: disable=redefined-outer-name
    ) -> Callable[[CANFrame], list[AmpioMessage] | None]:
        _state_decoders[frame_type] = fn
        return fn

    return _decorator


# ---------------------------------------------------------------------
# Codec
# ---------------------------------------------------------------------


class AmpioCodec:
    """Dispatch and decode Ampio FE frames into `AmpioMessage` items."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def decode(self, frame: CANFrame) -> list[AmpioMessage] | None:
        """Decode an Ampio frame.

        Returns:
            list[AmpioMessage]: recognized frame decoded
            []                  unrecognized/unsupported Ampio frame
            None                not-applicable (non-Ampio frame)
        """
        # SATEL device broadcast (0x10 ...)
        if len(frame.data) == 3 and frame.data[0] == _STATE_SATEL_FLAG:
            try:
                return _decode_satel_status(frame)
            except Exception:  # pylint: disable=broad-except
                # pragma: no cover - defensive
                self._logger.warning("Unknown SATEL frame: %s", frame.data.hex())

        # General Ampio device broadcast (0xFE ...)
        if len(frame.data) >= 2 and frame.data[0] == _STATE_FLAG:
            ftype = frame.data[1]
            try:
                decoder = _state_decoders.get(StateType(ftype))
                if decoder:
                    return decoder(frame)
            except ValueError:
                # First time we see a new state type -> log once
                if ftype not in _unknown_state_decoder:
                    self._logger.warning(
                        "Unknown state type: can_id=0x%08X ftype=0x%02X",
                        frame.can_id,
                        ftype,
                    )
                    _unknown_state_decoder.add(ftype)

        return []


# ---------------------------------------------------------------------
# SATEL status (0x10 EF xx)
# ---------------------------------------------------------------------


def _decode_satel_status(frame: CANFrame) -> list[AmpioMessage] | None:
    """Decode SATEL status triplet (0x10, 0xEF, status)."""
    if len(frame.data) >= 3 and frame.data[1] == 0xEF:
        status = frame.data[2]
        response = satel_response_to_str(status)
        return [
            AmpioMessage(
                topic=f"{frame.can_id:08x}.response.1",
                payload={"status": status, "response": response},
                raw=frame,
            )
        ]
    return []


# ---------------------------------------------------------------------
# Concrete decoders (single-topic)
# ---------------------------------------------------------------------


@register_state_decoder(StateType.DATETIME)
def _decode_datetime(frame: CANFrame) -> list[AmpioMessage] | None:
    """Decode FE datetime broadcast."""
    # Expect 8 bytes total: FE, type, y, m, d, wk, (daytime|hour), minute
    specs = (
        U8("year", 2, add=2000),  # 2000 + yy
        Mask("month", 3, 0x0F),  # low nibble
        Mask("day", 4, 0x1F),
        Mask("weekday", 5, 0x07),
        Mask("daytime", 6, 0x80),  # keep numeric (0 or 0x80)
        Mask("hour", 6, 0x1F),
        Mask("minute", 7, 0x7F),
    )
    payload = decode_payload(frame.data, specs)
    if payload is None:
        return []
    return [
        AmpioMessage(topic=f"{frame.can_id:08x}.datetime.1", payload=payload, raw=frame)
    ]


@register_state_decoder(StateType.DIAGNOSTICS)
def _decode_diagnostics(frame: CANFrame) -> list[AmpioMessage] | None:
    """Decode FE diagnostics (voltage/temperature)."""
    specs = (
        U8("voltage", 2, mul=0.2, ndigits=1),  # (d[2] << 1) / 10 == d[2]*0.2
        U8("temperature", 3, add=-100),
    )
    payload = decode_payload(frame.data, specs)
    if payload is None:
        return []
    return [
        AmpioMessage(
            topic=f"{frame.can_id:08x}.diagnostics.1", payload=payload, raw=frame
        )
    ]


@register_state_decoder(StateType.TEMPERATURE)
def _decode_temperature(frame: CANFrame) -> list[AmpioMessage] | None:
    """Decode FE temperature: ((u16le@2) - 1000) / 10 → °C."""
    specs = (
        U16("value", 2, add=-1000, mul=0.1, ndigits=2),
        Const("unit", "°C"),
    )
    payload = decode_payload(frame.data, specs)
    if payload is None:
        return []
    return [
        AmpioMessage(
            topic=f"{frame.can_id:08x}.temperature.1", payload=payload, raw=frame
        )
    ]


@register_state_decoder(StateType.RGB)
def _decode_rgb(frame: CANFrame) -> list[AmpioMessage] | None:
    """Decode FE RGB values (R,G,B,W)."""
    specs = (
        U8("red", 2),
        U8("green", 3),
        U8("blue", 4),
        U8("white", 5),
    )
    payload = decode_payload(frame.data, specs)
    if payload is None:
        return []
    return [AmpioMessage(topic=f"{frame.can_id:08x}.rgb.1", payload=payload, raw=frame)]


def _make_heating_zone(channel: int) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    """Create a decoder for a single heating zone."""

    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        specs = (
            U8("current_temperature", 2, mul=0.1),
            U8("target_temperature", 4, mul=0.1),
            # (s8 - 100) / 10     ← now explicitly signed via I8
            I8("temperature_diff", 6, add=-100, mul=0.1),
            BitFlag("active", 7, 0),
            BitFlag("heating", 7, 1),
            BitFlag("day_mode", 7, 2),
            Mask("mode", 7, 0x70),  # keep raw numeric (unchanged)
            EnumMasked("mode_name", 7, mask=0x70, shift=4, mapping=_HEATING_MODE_MAP),
        )
        payload = decode_payload(frame.data, specs)
        if payload is None:
            return []
        return [
            AmpioMessage(
                topic=f"{frame.can_id:08x}.heating.{channel}",
                payload=payload,
                raw=frame,
            )
        ]

    return decoder


# ---------------------------------------------------------------------
# Generic factories (series/bitfields)
# ---------------------------------------------------------------------


def _make_u8_repeat_series(
    *,
    topic: str,
    start_channel: int,
    end_channel: int,
    base_offset: int = 2,
    stride: int = 1,
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    """Create a series decoder (u8 per channel) using Repeat(U8)."""
    count = end_channel - start_channel + 1
    rep = Repeat(
        name="values",
        element_specs=(U8("value", 0, add=add, mul=mul, ndigits=ndigits),),
        count=count,
        base_offset=base_offset,
        stride=stride,
        sparse=False,  # stop at first incomplete
    )

    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        tmp: dict[str, object] = {}
        rep.extract(frame.data, tmp)
        items = tmp.get("values", [])  # type: ignore[assignment]
        out: list[AmpioMessage] = []
        for i, payload in enumerate(items):  # type: ignore[assignment]
            ch = start_channel + i  # pylint: disable=redefined-outer-name
            out.append(
                AmpioMessage(
                    topic=f"{frame.can_id:08x}.{topic}.{ch}",
                    payload=payload,  # {"value": ...}
                    raw=frame,
                )
            )
        return out

    return decoder


def _make_u16_repeat_series(
    *,
    topic: str,
    start_channel: int,
    end_channel: int,
    base_offset: int = 2,
    stride: int = 2,
    add: float = 0.0,
    mul: float = 1.0,
    ndigits: int | None = None,
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    """Create a series decoder (u16 per channel) using Repeat(U16)."""
    count = end_channel - start_channel + 1
    rep = Repeat(
        name="values",
        element_specs=(U16("value", 0, add=add, mul=mul, ndigits=ndigits),),
        count=count,
        base_offset=base_offset,
        stride=stride,
        sparse=False,  # stop at first incomplete
    )

    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        tmp: dict[str, object] = {}
        rep.extract(frame.data, tmp)
        items = tmp.get("values", [])  # type: ignore[assignment]
        out: list[AmpioMessage] = []
        for i, payload in enumerate(items):  # type: ignore[assignment]
            ch = start_channel + i  # pylint: disable=redefined-outer-name
            out.append(
                AmpioMessage(
                    topic=f"{frame.can_id:08x}.{topic}.{ch}",
                    payload=payload,  # {"value": ...}
                    raw=frame,
                )
            )
        return out

    return decoder


def _make_bitblock(
    start_channel: int, end_channel: int, topic: str
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    """Create a bit-field decoder across bytes starting at data[2]."""
    count = end_channel - start_channel + 1

    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        out: list[AmpioMessage] = []
        for i in range(count):
            byte_idx = 2 + (i // 8)
            bit_idx = i % 8
            spec = (BitFlag("state", byte_idx, bit_idx),)
            payload = decode_payload(frame.data, spec)
            if payload is None:
                break
            ch = start_channel + i  # pylint: disable=redefined-outer-name
            out.append(
                AmpioMessage(
                    topic=f"{frame.can_id:08x}.{topic}.{ch}",
                    payload=payload,
                    raw=frame,
                )
            )
        return out

    return decoder


# ---------------------------------------------------------------------
# Table-driven registration
# ---------------------------------------------------------------------

# Blocks of sequential channels with the same shape
_DECODER_TABLE: dict[StateType, Callable[[CANFrame], list[AmpioMessage] | None]] = {
    # aout.1..18 in 3 blocks (u8) via Repeat(U8)
    StateType.AOUT_1: _make_u8_repeat_series(
        topic="aout", start_channel=1, end_channel=6
    ),
    StateType.AOUT_2: _make_u8_repeat_series(
        topic="aout", start_channel=7, end_channel=12
    ),
    StateType.AOUT_3: _make_u8_repeat_series(
        topic="aout", start_channel=13, end_channel=18
    ),
    # s16b.* (u16 LE raw) via Repeat(U16)
    StateType.S16B_1: _make_u16_repeat_series(
        topic="s16b", start_channel=1, end_channel=3
    ),
    StateType.S16B_2: _make_u16_repeat_series(
        topic="s16b", start_channel=4, end_channel=6
    ),
    StateType.S16B_3: _make_u16_repeat_series(
        topic="s16b", start_channel=7, end_channel=9
    ),
    # s16b10000.* ( (u16 LE - 10000)/10 → 1 decimal ) via Repeat(U16)
    StateType.S16B10000_1: _make_u16_repeat_series(
        topic="s16b10000",
        start_channel=1,
        end_channel=3,
        add=-10000,
        mul=0.1,
        ndigits=1,
    ),
    StateType.S16B10000_2: _make_u16_repeat_series(
        topic="s16b10000",
        start_channel=4,
        end_channel=6,
        add=-10000,
        mul=0.1,
        ndigits=1,
    ),
    StateType.S16B10000_3: _make_u16_repeat_series(
        topic="s16b10000",
        start_channel=7,
        end_channel=9,
        add=-10000,
        mul=0.1,
        ndigits=1,
    ),
    StateType.S16B10000_4: _make_u16_repeat_series(
        topic="s16b10000",
        start_channel=10,
        end_channel=12,
        add=-10000,
        mul=0.1,
        ndigits=1,
    ),
    StateType.S16B10000_5: _make_u16_repeat_series(
        topic="s16b10000",
        start_channel=13,
        end_channel=15,
        add=-10000,
        mul=0.1,
        ndigits=1,
    ),
    # Bit fields / summaries
    StateType.BIN_1: _make_bitblock(1, 48, "bin"),
    StateType.BIN_2: _make_bitblock(49, 96, "bin"),
    StateType.BIN_3: _make_bitblock(97, 144, "bin"),
    StateType.BOUT_1: _make_bitblock(1, 48, "bout"),
    StateType.BOUT_2: _make_bitblock(49, 96, "bout"),
    StateType.BOUT_3: _make_bitblock(97, 144, "bout"),
    StateType.BINOUT: _make_bitblock(1, 48, "binout"),
    StateType.FLAG: _make_bitblock(1, 32, "flag"),
    StateType.HEATING_ZONE_SUMMARY: _make_bitblock(1, 16, "zone"),
}

# One-per-channel structured messages (heating zones)
_HEATING_MAP: dict[StateType, int] = {
    StateType.HEATING_ZONE_1: 1,
    StateType.HEATING_ZONE_2: 2,
    StateType.HEATING_ZONE_3: 3,
    StateType.HEATING_ZONE_4: 4,
    StateType.HEATING_ZONE_5: 5,
    StateType.HEATING_ZONE_6: 6,
    StateType.HEATING_ZONE_7: 7,
    StateType.HEATING_ZONE_8: 8,
    StateType.HEATING_ZONE_9: 9,
    StateType.HEATING_ZONE_10: 10,
    StateType.HEATING_ZONE_11: 11,
    StateType.HEATING_ZONE_12: 12,
    StateType.HEATING_ZONE_13: 13,
    StateType.HEATING_ZONE_14: 14,
    StateType.HEATING_ZONE_15: 15,
    StateType.HEATING_ZONE_16: 16,
}

# SATEL zone-like bit sets (1..8)
_SATEL_BIT_SETS: dict[StateType, str] = {
    StateType.SATEL_ARMED: "armed",
    StateType.SATEL_ALARM: "alarm",
    StateType.SATEL_BREACHED: "breached",
    StateType.SATEL_ARMING: "arming",
    StateType.SATEL_ARMING_10S: "arming_10s",
}

# Register all table entries
for st, fn in _DECODER_TABLE.items():
    register_state_decoder(st)(fn)

for st, ch in _HEATING_MAP.items():
    register_state_decoder(st)(_make_heating_zone(ch))

for st, name in _SATEL_BIT_SETS.items():
    register_state_decoder(st)(_make_bitblock(1, _MAX_SATEL_ZONES, name))

# Register the codec with the global registry
registry().register(AmpioCodec())
