"""Capture outgoing command frames without opening a physical CAN bus."""

import asyncio
from unittest.mock import AsyncMock, patch

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


async def test_rgbw_bursts_are_paced_and_do_not_interleave() -> None:
    """Avoid dropping channels when rapid off/on commands share a module."""
    bridge = await make_bridge(model=12)
    light = bridge.lights["00000123_light1"]
    light.color = True
    entered = asyncio.Event()
    release = asyncio.Event()
    real_sleep = asyncio.sleep
    now = 100.0
    sent = []

    async def sleep(delay: float) -> None:
        nonlocal now
        now += delay
        await real_sleep(0)

    async def send(can_id: int, *, data: bytes) -> None:
        sent.append((now, can_id, data.hex()))
        if not entered.is_set():
            entered.set()
            await release.wait()
        await real_sleep(0)

    bridge.send.side_effect = send
    with (
        patch(
            "aioampio.controllers.lights.monotonic",
            side_effect=lambda: now,
            create=True,
        ),
        patch("asyncio.sleep", side_effect=sleep),
    ):
        off = asyncio.create_task(bridge.lights.set_state(light.id, on=False))
        await asyncio.wait_for(entered.wait(), timeout=1)
        on = asyncio.create_task(
            bridge.lights.set_state(light.id, color=(64, 32, 16, 8))
        )
        try:
            await real_sleep(0)
        finally:
            release.set()
            await asyncio.gather(off, on)
    expected = [f"000001231500{channel:02x}" for channel in range(4)] + [
        f"0000012315{level:02x}{channel:02x}"
        for channel, level in enumerate((64, 32, 16, 8))
    ]
    assert [frame for _, _, frame in sent] == expected
    assert all(can_id == 0x0F000000 for _, can_id, _ in sent)
    assert all(
        after[0] - before[0] >= 0.009999 for before, after in zip(sent, sent[1:])
    )


async def test_alarm_transactions_are_paced_and_serialized() -> None:
    """Keep each arm/disarm frame sequence complete with a gap between its frames."""
    bridge = await make_bridge()
    real_sleep = asyncio.sleep
    events = []

    async def send(_can_id: int, *, data: bytes) -> None:
        events.append(("send", data[5]))
        await real_sleep(0)

    async def sleep(delay: float) -> None:
        events.append(("sleep", delay))
        await real_sleep(0)

    bridge.send.side_effect = send
    with patch("aioampio.controllers.base.asyncio.sleep", side_effect=sleep):
        await asyncio.gather(
            bridge.alarm_control_panels.arm_in_mode0("00000123_alarm1", "1234"),
            bridge.alarm_control_panels.disarm("00000123_alarm1", "1234"),
        )
    expected = []
    for _ in range(2):
        for sequence in range(9):
            if sequence:
                expected.append(("sleep", 0.01))
            expected.append(("send", sequence))
    assert events == expected
    frames = bridge.send.await_args_list
    for offset, command in [(0, 0x80), (9, 0x84)]:
        payload = b"".join(
            c.kwargs["data"][6:] for c in frames[offset + 1 : offset + 9]
        )
        assert payload == bytes((0x14, 0x0D, command)) + bytes.fromhex(
            "1234ffffffffffff01000000"
        )


async def test_alarm_send_failure_stops_transaction_and_releases_lock() -> None:
    """A failed frame aborts once and the next explicit command can still run."""
    bridge = await make_bridge()
    bridge.send.side_effect = [None, None, ConnectionError("test failure")]
    with pytest.raises(ConnectionError, match="test failure"):
        await bridge.alarm_control_panels.arm_in_mode0("00000123_alarm1", "1234")
    assert bridge.send.await_count == 3
    bridge.send.reset_mock(side_effect=True)
    await asyncio.wait_for(
        bridge.alarm_control_panels.disarm("00000123_alarm1", "1234"), timeout=1
    )
    assert bridge.send.await_count == 9
