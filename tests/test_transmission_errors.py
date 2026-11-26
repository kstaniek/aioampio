"""Public commands report rejected transport writes without HA dependencies."""

from unittest.mock import AsyncMock

import pytest

from aioampio import AmpioBridge, AmpioTransmissionError


async def test_offline_send_raises() -> None:
    bridge = AmpioBridge({}, interface="virtual", channel="no-physical-io")
    await bridge.initialize()
    with pytest.raises(AmpioTransmissionError):
        await bridge.send(0x123, b"x")
    assert bridge.metrics.tx_total == 0


async def test_multiframe_command_stops_at_first_failed_frame() -> None:
    bridge = AmpioBridge(
        {
            "devices": [
                {
                    "can_id": 0x123,
                    "name": "Test module",
                    "model": 4,
                    "covers": [
                        {"id": "cover1", "name": "Test cover", "states": ["aout.1"]}
                    ],
                }
            ]
        },
        interface="virtual",
        channel="no-physical-io",
    )
    await bridge.initialize()
    bridge._tx_handler.send = AsyncMock(side_effect=[True, False, True])
    with pytest.raises(AmpioTransmissionError):
        await bridge.covers.open_cover("00000123_cover1")
    assert bridge._tx_handler.send.await_count == 2
