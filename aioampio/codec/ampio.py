"""Ampio state frame codec and router."""

from __future__ import annotations
import logging
from enum import Enum, unique
from collections.abc import Callable


from .base import AmpioMessage, Codec, CANFrame
from .registry import register_codec

log = logging.getLogger(__name__)


_STATE_FLAG = 0xFE  # data[0] - device broadcast
_STATE_SATEL_FLAG = 0x10  # data[0] - SATEL device broadcast

_MAX_SATEL_ZONES = 8

_state_decoders: dict[StateType, Callable[[CANFrame], list[AmpioMessage] | None]] = {}
_unknown_state_decoder: set[int] = set()


@unique
class StateType(Enum):
    """Enum for Ampio state types."""

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
    DIAGNOSTICS = 0x4F  # fe_4f_38_85 V=11.2 T=33
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


# SATEL response code to string mapping
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
    """Convert SATEL response code to string."""
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
    """Decorate to register a decoder for a specific Ampio state type frame.

    Usage:
        @register_state_decoder(0x01)
        def decode_temp(frame: CANFrame) -> list[AmpioMessage] | None:
            ...
    """

    def _decorator(
        fn: Callable[[CANFrame], list[AmpioMessage] | None],
    ) -> Callable[[CANFrame], list[AmpioMessage] | None]:
        _state_decoders[frame_type] = fn
        return fn

    return _decorator


class StateFrameRouter(Codec):
    """Dispatches incoming CAN frames with data[0]=0xFE to the appropriate state decoder."""

    def __init__(self) -> None:
        super().__init__()
        self._logger = logging.getLogger(__name__)

    def decode(self, frame: CANFrame) -> list[AmpioMessage] | None:
        if len(frame.data) == 3 and frame.data[0] == _STATE_SATEL_FLAG:
            # Handle SATEL specific decoding
            try:
                return _decode_satel_status(frame)
            except Exception:  # pylint: disable=broad-except
                self._logger.warning(
                    "Unknown SATEL frame received: %s", frame.data.hex()
                )

        if len(frame.data) >= 2 and frame.data[0] == _STATE_FLAG:
            ftype = frame.data[1]
            try:
                decoder = _state_decoders.get(StateType(ftype))
                if decoder:
                    return decoder(frame)
            except ValueError:
                # checking because wanted to log only if new
                if ftype not in _unknown_state_decoder:
                    self._logger.warning(
                        "Unknown state type: can_id=0x%08X ftype=0x%02X",
                        frame.can_id,
                        ftype,
                    )
                    _unknown_state_decoder.add(ftype)

        return None


def _decode_satel_status(frame: CANFrame) -> list[AmpioMessage] | None:
    if len(frame.data) >= 3:
        if frame.data[1] != 0xEF:  # satel status
            return None
        status = frame.data[2]
        response = satel_response_to_str(status)
        return [
            AmpioMessage(
                topic=f"{frame.can_id:08x}.response.1",
                payload={"status": status, "response": response},
                raw=frame,
            )
        ]
    return None


@register_state_decoder(StateType.DATETIME)  # DateTime
def _decode_datetime(frame: CANFrame) -> list[AmpioMessage] | None:
    if len(frame.data) == 8:
        d = frame.data
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
    return None


@register_state_decoder(StateType.DIAGNOSTICS)  # Diagnostics
def _decode_diagnostics(frame: CANFrame) -> list[AmpioMessage] | None:
    if len(frame.data) == 4:
        voltage = round(float(frame.data[2] << 1) / 10, 1)
        temperature = frame.data[3] - 100
        return [
            AmpioMessage(
                topic=f"{frame.can_id:08x}.diagnostics.1",
                payload={"voltage": voltage, "temperature": temperature},
                raw=frame,
            )
        ]
    return None


@register_state_decoder(StateType.TEMPERATURE)  # Temperature
def _decode_temperature(frame: CANFrame) -> list[AmpioMessage] | None:
    if len(frame.data) >= 3:
        high = frame.data[2]
        low = frame.data[3]
        raw_temp = ((low << 8) | high) - 1000
        temperature = round(raw_temp / 10, 2)
        return [
            AmpioMessage(
                topic=f"{frame.can_id:08x}.temperature.1",
                payload={"value": temperature, "unit": "°C"},
                raw=frame,
            )
        ]
    return None


@register_state_decoder(StateType.RGB)  # RGB
def _decode_rgb(frame: CANFrame) -> list[AmpioMessage] | None:
    if len(frame.data) >= 6:
        r = frame.data[2]
        g = frame.data[3]
        b = frame.data[4]
        w = frame.data[5]
        return [
            AmpioMessage(
                topic=f"{frame.can_id:08x}.rgb.1",
                payload={"red": r, "green": g, "blue": b, "white": w},
                raw=frame,
            )
        ]
    return None


def _decode_signed16b_factory(
    start_channel: int, end_channel: int
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        msg: list[AmpioMessage] = []
        for channel in range(start_channel, end_channel + 1):
            idx = 2 + 2 * (channel - start_channel)
            if 0 <= idx < len(frame.data):
                low = int(frame.data[idx])
                high = int(frame.data[idx + 1])
                value = (high << 8) | low
                msg.append(
                    AmpioMessage(
                        topic=f"{frame.can_id:08x}.s16b.{channel}",
                        payload={"value": value},
                        raw=frame,
                    )
                )
        return msg

    return decoder


register_state_decoder(StateType.S16B_1)(_decode_signed16b_factory(1, 3))
register_state_decoder(StateType.S16B_2)(_decode_signed16b_factory(4, 6))
register_state_decoder(StateType.S16B_3)(_decode_signed16b_factory(7, 9))


def _decode_analog_output_factory(
    start_channel: int, end_channel: int
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        msg: list[AmpioMessage] = []
        for channel in range(start_channel, end_channel + 1):
            idx = 2 + (channel - start_channel)
            if 0 <= idx < len(frame.data):
                value = int(frame.data[idx])
                msg.append(
                    AmpioMessage(
                        topic=f"{frame.can_id:08x}.aout.{channel}",
                        payload={"value": value},
                        raw=frame,
                    )
                )
        return msg

    return decoder


register_state_decoder(StateType.AOUT_1)(_decode_analog_output_factory(1, 6))
register_state_decoder(StateType.AOUT_2)(_decode_analog_output_factory(7, 12))
register_state_decoder(StateType.AOUT_3)(_decode_analog_output_factory(13, 18))


def _decode_signed16b10000_factory(
    start_channel: int, end_channel: int
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        msg: list[AmpioMessage] = []
        for channel in range(start_channel, end_channel + 1):
            idx = 2 + 2 * (channel - start_channel)
            if 0 <= idx < len(frame.data):
                low = int(frame.data[idx])
                high = int(frame.data[idx + 1])
                data = (high << 8) | low
                value = round(float((data - 10000) / 10), 1)
                msg.append(
                    AmpioMessage(
                        topic=f"{frame.can_id:08x}.s16b10000.{channel}",
                        payload={"value": value},
                        raw=frame,
                    )
                )
        return msg

    return decoder


register_state_decoder(StateType.S16B10000_1)(_decode_signed16b10000_factory(1, 3))
register_state_decoder(StateType.S16B10000_2)(_decode_signed16b10000_factory(4, 6))
register_state_decoder(StateType.S16B10000_3)(_decode_signed16b10000_factory(7, 9))


def _decode_satel_binary_factory(
    start_channel: int, end_channel: int, name: str
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        if len(frame.data) > 2:
            msg: list[AmpioMessage] = []
            for i, channel in enumerate(range(start_channel, end_channel + 1)):
                byte_idx = 2 + (i // 8)
                if byte_idx >= len(frame.data):
                    break
                bit_idx = i % 8
                value = bool(frame.data[byte_idx] & (1 << bit_idx))
                msg.append(
                    AmpioMessage(
                        topic=f"{frame.can_id:08x}.{name}.{channel}",
                        payload={"state": value},
                        raw=frame,
                    )
                )
            return msg
        return None

    return decoder


register_state_decoder(StateType.BIN_1)(_decode_satel_binary_factory(1, 48, "bin"))
register_state_decoder(StateType.BIN_2)(_decode_satel_binary_factory(49, 96, "bin"))
register_state_decoder(StateType.BIN_3)(_decode_satel_binary_factory(97, 144, "bin"))
register_state_decoder(StateType.BOUT_1)(_decode_satel_binary_factory(1, 48, "bout"))
register_state_decoder(StateType.BOUT_2)(_decode_satel_binary_factory(49, 96, "bout"))
register_state_decoder(StateType.BOUT_3)(_decode_satel_binary_factory(97, 144, "bout"))
register_state_decoder(StateType.BINOUT)(_decode_satel_binary_factory(1, 48, "binout"))
# # FE 39 04 00 00 00 <- zone 3
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


def _decode_heating_zone_factory(
    channel: int, name: str
) -> Callable[[CANFrame], list[AmpioMessage] | None]:
    def decoder(frame: CANFrame) -> list[AmpioMessage] | None:
        msg: list[AmpioMessage] = []
        # temp measured
        temp_measured = (
            int.from_bytes(frame.data[2:3], byteorder="little", signed=False) / 10
        )
        # temp setpoint
        temp_setpoint = (
            int.from_bytes(frame.data[4:5], byteorder="little", signed=False) / 10
        )
        # control mode
        diff = (
            int.from_bytes(frame.data[6:7], byteorder="little", signed=True) / 10 - 10
        )

        zone_params = frame.data[7]
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


register_state_decoder(StateType.HEATING_ZONE_1)(
    _decode_heating_zone_factory(1, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_2)(
    _decode_heating_zone_factory(2, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_3)(
    _decode_heating_zone_factory(3, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_4)(
    _decode_heating_zone_factory(4, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_5)(
    _decode_heating_zone_factory(5, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_6)(
    _decode_heating_zone_factory(6, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_7)(
    _decode_heating_zone_factory(7, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_8)(
    _decode_heating_zone_factory(8, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_9)(
    _decode_heating_zone_factory(9, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_10)(
    _decode_heating_zone_factory(10, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_11)(
    _decode_heating_zone_factory(11, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_12)(
    _decode_heating_zone_factory(12, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_13)(
    _decode_heating_zone_factory(13, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_14)(
    _decode_heating_zone_factory(14, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_15)(
    _decode_heating_zone_factory(15, "heating")
)
register_state_decoder(StateType.HEATING_ZONE_16)(
    _decode_heating_zone_factory(16, "heating")
)

register_codec(StateFrameRouter())
