# aioampio/codec/ampio.py
"""Ampio state frame codec and router."""

from __future__ import annotations
import logging
from enum import Enum, unique
from collections.abc import Callable

from .base import AmpioMessage, CANFrame
from .registry import registry, FrameDecoder

log = logging.getLogger(__name__)

_STATE_FLAG = 0xFE  # data[0] - Ampio device broadcast
_STATE_SATEL_FLAG = 0x10  # data[0] - SATEL device broadcast
_MAX_SATEL_ZONES = 8

_state_decoders: dict["StateType", Callable[[CANFrame], list[AmpioMessage] | None]] = {}
_unknown_state_decoder: set[int] = set()


@unique
class StateType(Enum):
    """Known Ampio state frame types (data[1])."""

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


SATEL_RESPONSE_MAP = {
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


def satel_response_to_str(value: int) -> str:
    """Translate SATEL response code to human-readable string."""
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
    """Decorator to register a state frame decoder for given type."""

    def _decorator(
        fn: Callable[[CANFrame], list[AmpioMessage] | None],
    ) -> Callable[[CANFrame], list[AmpioMessage] | None]:
        _state_decoders[frame_type] = fn
        return fn

    return _decorator


# --------------------------- SATEL codec ---------------------------------


class SatelCodec(FrameDecoder):
    """Decodes SATEL 0x10 EF status frames."""

    def matches(self, frame: CANFrame) -> bool:  # optional fast-path
        """Quick pre-check if this frame might be SATEL status."""
        return len(frame.data) >= 3 and frame.data[0] == _STATE_SATEL_FLAG

    def decode(self, frame: CANFrame):
        """Decode SATEL status response frames."""
        d = frame.data
        if len(d) < 3 or d[1] != 0xEF:
            return []
        status = d[2]
        response = satel_response_to_str(status)
        return [
            AmpioMessage(
                topic=f"{frame.can_id:08x}.response.1",
                payload={"status": status, "response": response},
                raw=frame,
            )
        ]


# ------------------------- Ampio state codec -----------------------------


class AmpioStateCodec(FrameDecoder):
    """Routes FE <type> ... frames to registered per-type decoders."""

    def __init__(self) -> None:
        self._logger = logging.getLogger(__name__)

    def matches(self, frame: CANFrame) -> bool:
        """Quick pre-check if this frame might be Ampio state."""
        d = frame.data
        return len(d) >= 2 and d[0] == _STATE_FLAG

    def decode(self, frame: CANFrame):
        """Decode Ampio state frames by routing to registered decoders."""
        d = frame.data
        if len(d) < 2 or d[0] != _STATE_FLAG:
            return []

        ftype = d[1]
        try:
            stype = StateType(ftype)
        except ValueError:
            # log each unknown once
            if ftype not in _unknown_state_decoder:
                self._logger.warning(
                    "Unknown state type: can_id=0x%08X ftype=0x%02X",
                    frame.can_id,
                    ftype,
                )
                _unknown_state_decoder.add(ftype)
            return []

        decoder = _state_decoders.get(stype)
        if not decoder:
            return []
        try:
            out = decoder(frame)
            return out or []
        except (
            Exception  # pylint: disable=broad-except
        ):  # defensive isolation around user decoders
            self._logger.exception("State decoder %s failed", st.name)
            return []


# ----------------------------- Decoders ----------------------------------


@register_state_decoder(StateType.DATETIME)
def _decode_datetime(frame: CANFrame):
    d = frame.data
    if len(d) != 8:
        return []
    year = 2000 + d[2]
    month = d[3] & 0x0F
    day = d[4] & 0x1F
    weekday = d[5] & 0x07
    daytime = d[6] & 0x80
    hour = d[6] & 0x1F
    minute = d[7] & 0x7F
    return [
        AmpioMessage(
            topic=f"{frame.can_id:08x}.datetime.1",
            payload={
                "year": year,
                "month": month,
                "day": day,
                "weekday": weekday,
                "daytime": daytime,
                "hour": hour,
                "minute": minute,
            },
            raw=frame,
        )
    ]


@register_state_decoder(StateType.DIAGNOSTICS)
def _decode_diagnostics(frame: CANFrame):
    d = frame.data
    if len(d) != 4:
        return []
    voltage = round(float(d[2] << 1) / 10, 1)
    temperature = d[3] - 100
    return [
        AmpioMessage(
            topic=f"{frame.can_id:08x}.diagnostics.1",
            payload={"voltage": voltage, "temperature": temperature},
            raw=frame,
        )
    ]


@register_state_decoder(StateType.TEMPERATURE)
def _decode_temperature(frame: CANFrame):
    d = frame.data
    if len(d) < 4:
        return []
    high = d[2]
    low = d[3]
    raw_temp = ((low << 8) | high) - 1000
    temperature = round(raw_temp / 10, 2)
    return [
        AmpioMessage(
            topic=f"{frame.can_id:08x}.temperature.1",
            payload={"value": temperature, "unit": "°C"},
            raw=frame,
        )
    ]


@register_state_decoder(StateType.RGB)
def _decode_rgb(frame: CANFrame):
    d = frame.data
    if len(d) < 6:
        return []
    r, g, b, w = d[2], d[3], d[4], d[5]
    return [
        AmpioMessage(
            topic=f"{frame.can_id:08x}.rgb.1",
            payload={"red": r, "green": g, "blue": b, "white": w},
            raw=frame,
        )
    ]


def _decode_signed16b_factory(start_channel: int, end_channel: int):
    def decoder(frame: CANFrame):
        d = frame.data
        msg: list[AmpioMessage] = []
        for channel in range(start_channel, end_channel + 1):
            idx = 2 + 2 * (channel - start_channel)
            if idx + 1 >= len(d):
                break
            low = int(d[idx])
            high = int(d[idx + 1])
            # NOTE: original treated as unsigned; keep behavior
            val = (high << 8) | low
            msg.append(
                AmpioMessage(
                    topic=f"{frame.can_id:08x}.s16b.{channel}",
                    payload={"value": val},
                    raw=frame,
                )
            )
        return msg

    return decoder


register_state_decoder(StateType.S16B_1)(_decode_signed16b_factory(1, 3))
register_state_decoder(StateType.S16B_2)(_decode_signed16b_factory(4, 6))
register_state_decoder(StateType.S16B_3)(_decode_signed16b_factory(7, 9))


def _decode_analog_output_factory(start_channel: int, end_channel: int):
    def decoder(frame: CANFrame):
        d = frame.data
        msg: list[AmpioMessage] = []
        for ch in range(start_channel, end_channel + 1):
            idx = 2 + (ch - start_channel)
            if idx >= len(d):
                break
            msg.append(
                AmpioMessage(
                    topic=f"{frame.can_id:08x}.aout.{ch}",
                    payload={"value": int(d[idx])},
                    raw=frame,
                )
            )
        return msg

    return decoder


register_state_decoder(StateType.AOUT_1)(_decode_analog_output_factory(1, 6))
register_state_decoder(StateType.AOUT_2)(_decode_analog_output_factory(7, 12))
register_state_decoder(StateType.AOUT_3)(_decode_analog_output_factory(13, 18))


def _decode_signed16b10000_factory(start_channel: int, end_channel: int):
    def decoder(frame: CANFrame):
        d = frame.data
        msg: list[AmpioMessage] = []
        for ch in range(start_channel, end_channel + 1):
            idx = 2 + 2 * (ch - start_channel)
            if idx + 1 >= len(d):
                break
            low = int(d[idx])
            high = int(d[idx + 1])
            data = (high << 8) | low
            value = round(float((data - 10000) / 10), 1)
            msg.append(
                AmpioMessage(
                    topic=f"{frame.can_id:08x}.s16b10000.{ch}",
                    payload={"value": value},
                    raw=frame,
                )
            )
        return msg

    return decoder


register_state_decoder(StateType.S16B10000_1)(_decode_signed16b10000_factory(1, 3))
register_state_decoder(StateType.S16B10000_2)(_decode_signed16b10000_factory(4, 6))
register_state_decoder(StateType.S16B10000_3)(_decode_signed16b10000_factory(7, 9))
register_state_decoder(StateType.S16B10000_4)(_decode_signed16b10000_factory(10, 12))
register_state_decoder(StateType.S16B10000_5)(_decode_signed16b10000_factory(13, 15))


def _decode_satel_binary_factory(start_channel: int, end_channel: int, name: str):
    def decoder(frame: CANFrame):
        d = frame.data
        if len(d) <= 2:
            return []
        msg: list[AmpioMessage] = []
        for i, ch in enumerate(range(start_channel, end_channel + 1)):
            byte_idx = 2 + (i // 8)
            if byte_idx >= len(d):
                break
            bit_idx = i % 8
            value = bool(d[byte_idx] & (1 << bit_idx))
            msg.append(
                AmpioMessage(
                    topic=f"{frame.can_id:08x}.{name}.{ch}",
                    payload={"state": value},
                    raw=frame,
                )
            )
        return msg

    return decoder


register_state_decoder(StateType.BIN_1)(_decode_satel_binary_factory(1, 48, "bin"))
register_state_decoder(StateType.BIN_2)(_decode_satel_binary_factory(49, 96, "bin"))
register_state_decoder(StateType.BIN_3)(_decode_satel_binary_factory(97, 144, "bin"))
register_state_decoder(StateType.BOUT_1)(_decode_satel_binary_factory(1, 48, "bout"))
register_state_decoder(StateType.BOUT_2)(_decode_satel_binary_factory(49, 96, "bout"))
register_state_decoder(StateType.BOUT_3)(_decode_satel_binary_factory(97, 144, "bout"))
register_state_decoder(StateType.BINOUT)(_decode_satel_binary_factory(1, 48, "binout"))
register_state_decoder(StateType.SATEL_ARMING)(
    _decode_satel_binary_factory(1, _MAX_SATEL_ZONES, "arming")
)
register_state_decoder(StateType.SATEL_ARMING_10S)(
    _decode_satel_binary_factory(1, _MAX_SATEL_ZONES, "arming_10s")
)
register_state_decoder(StateType.SATEL_ARMED)(
    _decode_satel_binary_factory(1, _MAX_SATEL_ZONES, "armed")
)
register_state_decoder(StateType.SATEL_ALARM)(
    _decode_satel_binary_factory(1, _MAX_SATEL_ZONES, "alarm")
)
register_state_decoder(StateType.SATEL_BREACHED)(
    _decode_satel_binary_factory(1, _MAX_SATEL_ZONES, "breached")
)
register_state_decoder(StateType.FLAG)(_decode_satel_binary_factory(1, 32, "flag"))
register_state_decoder(StateType.HEATING_ZONE_SUMMARY)(
    _decode_satel_binary_factory(1, 16, "zone")
)


def _decode_heating_zone_factory(channel: int, name: str):
    def decoder(frame: CANFrame):
        d = frame.data
        msg: list[AmpioMessage] = []
        temp_measured = d[2] / 10
        temp_setpoint = d[4] / 10
        diff = (int.from_bytes(d[6:7], "little", signed=True) / 10) - 10
        zone_params = d[7]
        active = bool(zone_params & 0x01)
        heating = bool(zone_params & 0x02)
        day_mode = bool(zone_params & 0x04)
        mode = zone_params & 0x70
        msg.append(
            AmpioMessage(
                topic=f"{frame.can_id:08x}.{name}.{channel}",
                payload={
                    "current_temperature": temp_measured,
                    "target_temperature": temp_setpoint,
                    "temperature_diff": diff,
                    "active": active,
                    "heating": heating,
                    "day_mode": day_mode,
                    "mode": mode,
                },
                raw=frame,
            )
        )
        return msg

    return decoder


for index, st in enumerate(
    (
        StateType.HEATING_ZONE_1,
        StateType.HEATING_ZONE_2,
        StateType.HEATING_ZONE_3,
        StateType.HEATING_ZONE_4,
        StateType.HEATING_ZONE_5,
        StateType.HEATING_ZONE_6,
        StateType.HEATING_ZONE_7,
        StateType.HEATING_ZONE_8,
        StateType.HEATING_ZONE_9,
        StateType.HEATING_ZONE_10,
        StateType.HEATING_ZONE_11,
        StateType.HEATING_ZONE_12,
        StateType.HEATING_ZONE_13,
        StateType.HEATING_ZONE_14,
        StateType.HEATING_ZONE_15,
        StateType.HEATING_ZONE_16,
    ),
    start=1,
):
    register_state_decoder(st)(_decode_heating_zone_factory(index, "heating"))

# Register both codecs with the global registry (order doesn't matter with matches())
registry().register(SatelCodec())
registry().register(AmpioStateCodec())
