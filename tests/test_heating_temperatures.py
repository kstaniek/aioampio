"""Regress heating-zone temperature fields at the CAN boundary."""

import pytest

from aioampio.codec.ampio import AmpioCodec
from aioampio.codec.base import CANFrame


@pytest.mark.parametrize("zone", range(1, 17))
@pytest.mark.parametrize(
    ("current", "target", "difference"),
    [
        (22.3, 20.0, -2.3),
        (-12.3, 27.2, 13.8),
        (0.0, 0.0, 0.0),
        (25.5, 25.6, 0.1),
        (50.0, -10.0, -10.0),
    ],
)
def test_heating_temperature_fields(
    zone: int, current: float, target: float, difference: float
) -> None:
    """Decode both bytes, the 1000 offset, and an unsigned difference byte."""
    data = (
        bytes((0xFE, 0xC8 + zone))
        + round(current * 10 + 1000).to_bytes(2, "little")
        + round(target * 10 + 1000).to_bytes(2, "little")
        + bytes((round(difference * 10 + 100), 0x27))
    )
    messages = AmpioCodec().decode(CANFrame(0x1B88, memoryview(data)))
    assert messages is not None
    assert len(messages) == 1
    message = messages[0]
    assert message.topic == f"00001b88.heating.{zone}"
    assert message.payload == {
        "current_temperature": current,
        "target_temperature": target,
        "temperature_diff": difference,
        "active": True,
        "heating": True,
        "day_mode": True,
        "mode": 0x20,
        "operating_mode": 2,
        "mode_name": "mode2",
    }


@pytest.mark.parametrize("length", range(8))
def test_truncated_heating_frame(length: int) -> None:
    """Ignore incomplete zone reports instead of publishing partial values."""
    data = memoryview(bytes.fromhex("fe cb c7 04 b0 04 4d 05")[:length])
    assert AmpioCodec().decode(CANFrame(0x1B88, data)) == []
