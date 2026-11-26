"""Capture outgoing command frames without opening a physical CAN bus."""

from unittest.mock import AsyncMock

import pytest

from aioampio import AmpioBridge


async def make_bridge(model: int = 4) -> AmpioBridge:
    """Load real controllers and redirect their final CAN writes into a capture."""
    config = {
        "devices": [
            {
                "can_id": 0x123,
                "name": "Test",
                "model": model,
                "lights": [
                    {"id": "light1", "name": "light1", "states": ["aout.1", "binout.1"]}
                ],
                "switches": [
                    {"id": "switch1", "name": "switch1", "states": ["binout.1"]}
                ],
                "covers": [{"id": "cover1", "name": "cover1", "states": ["aout.1"]}],
                "valves": [{"id": "valve1", "name": "valve1", "states": ["aout.1"]}],
                "alarm_control_panels": [
                    {"id": "alarm1", "name": "alarm1", "states": ["armed.1"]}
                ],
            }
        ]
    }
    bridge = AmpioBridge(config, interface="virtual", channel="commands")
    await bridge.initialize()
    bridge.send = AsyncMock()
    return bridge


@pytest.mark.parametrize(
    ("on", "payload"), [(True, "0000012315ff00"), (False, "00000123150000")]
)
async def test_switch_frames(on: bool, payload: str) -> None:
    """Retain the existing single-frame binary output wire format."""
    bridge = await make_bridge()
    await bridge.switches.set_state("00000123_switch1", on=on)
    bridge.send.assert_awaited_once_with(0x0F000000, data=bytes.fromhex(payload))


async def test_brightness_command_after_received_state() -> None:
    """Round-trip a received brightness through the actual command encoder."""
    bridge = await make_bridge()
    light = bridge.lights["00000123_light1"]
    light.update("00000123.aout.1", {"value": 128})
    await bridge.lights.set_state(light.id, brightness=light.state["brightness"])
    bridge.send.assert_awaited_once_with(
        0x0F000000, data=bytes.fromhex("0000012315800000")
    )


@pytest.mark.parametrize(
    ("method", "frames"),
    [
        ("open_cover", ["000001231600022c", "00000123160131f9", "0000012316020200"]),
        ("close_cover", ["000001231600022b", "00000123160131f9", "0000012316020100"]),
        ("stop_cover", ["000001231600022a", "00000123160131f9", "0000012316020000"]),
    ],
)
async def test_cover_multiframe_commands(method: str, frames: list[str]) -> None:
    """Verify sequence numbers, checksum, target address, and motor command bytes."""
    bridge = await make_bridge()
    await getattr(bridge.covers, method)("00000123_cover1")
    assert [
        (call.args[0], call.kwargs["data"].hex())
        for call in bridge.send.await_args_list
    ] == [(0x0F000000, frame) for frame in frames]


async def test_valve_position_command() -> None:
    """Use the ignore sentinel for tilt when setting a valve position."""
    bridge = await make_bridge()
    await bridge.valves.set_position("00000123_valve1", position=50)
    assert [call.kwargs["data"].hex() for call in bridge.send.await_args_list] == [
        "00000123160004cb",
        "0000012316013103",
        "0000012316020000",
        "0000012316030032",
        "00000123160465",
    ]


async def test_rgb_channels_are_encoded_in_order() -> None:
    """Target the four RGBW channels with integer byte values."""
    bridge = await make_bridge(model=12)
    light = bridge.lights["00000123_light1"]
    light.color = True
    await bridge.lights.set_state(light.id, color=(10, 20, 30, 40))
    assert [call.kwargs["data"].hex() for call in bridge.send.await_args_list] == [
        "00000123150a00",
        "00000123151401",
        "00000123151e02",
        "00000123152803",
    ]


async def test_alarm_pin_and_zone_mask_are_not_sent_to_hardware() -> None:
    """Capture arm command framing and verify rejected PINs generate no frames."""
    bridge = await make_bridge()
    await bridge.alarm_control_panels.arm_in_mode0("00000123_alarm1", "1234")
    frames = bridge.send.await_args_list
    assert all(call.args[0] == 0x0F000000 for call in frames)
    payload = b"".join(call.kwargs["data"][6:] for call in frames[1:])
    assert payload == bytes.fromhex("140d801234ffffffffffff01000000")
    bridge.send.reset_mock()
    await bridge.alarm_control_panels.disarm("00000123_alarm1", "invalid")
    bridge.send.assert_not_awaited()
