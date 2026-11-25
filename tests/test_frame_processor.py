"""Verify the shared frame processor is the bridge's actual receive path."""

from unittest.mock import Mock

import can
import pytest

from aioampio import AmpioBridge
from aioampio.codec.base import AmpioMessage, CANFrame
from aioampio import rx_workers


@pytest.mark.parametrize(
    "options",
    [
        {"is_extended_id": False},
        {"is_remote_frame": True},
        {"is_error_frame": True},
        {"dlc": 3},
        {"data": b""},
    ],
)
async def test_invalid_frames_are_not_decoded(
    monkeypatch: pytest.MonkeyPatch, options: dict
) -> None:
    """Ignore control/error frames, invalid lengths, and empty data before decoding."""
    decoder = Mock()
    monkeypatch.setattr(rx_workers, "registry", Mock(return_value=decoder))
    bridge = AmpioBridge({}, interface="virtual", channel="test")
    arguments = {"arbitration_id": 123, "data": b"x", "is_extended_id": True, **options}
    await bridge._on_frame(can.Message(**arguments))
    decoder.decode.assert_not_called()


async def test_decoded_messages_reach_store_in_order(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Route the shared processor through the real bridge and state store."""
    raw = CANFrame(123, memoryview(b"x"))
    decoder = Mock()
    decoder.decode.return_value = [AmpioMessage(raw, 1, "a"), AmpioMessage(raw, 2, "b")]
    monkeypatch.setattr(rx_workers, "registry", Mock(return_value=decoder))
    bridge = AmpioBridge({}, interface="virtual", channel="test")
    observed = []
    bridge.state_store.on_change(lambda _event, data: observed.append(data["topic"]))
    await bridge._on_frame(
        can.Message(arbitration_id=123, data=b"x", is_extended_id=True)
    )
    assert observed == ["a", "b"]
    assert bridge.state_store.snapshot() == {"a": 1, "b": 2}


async def test_decoder_error_does_not_prevent_next_frame(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A decoder error is isolated so the next valid message can be processed."""
    raw = CANFrame(123, memoryview(b"x"))
    decoder = Mock()
    decoder.decode.side_effect = [
        ValueError("bad frame"),
        [AmpioMessage(raw, True, "a")],
    ]
    monkeypatch.setattr(rx_workers, "registry", Mock(return_value=decoder))
    bridge = AmpioBridge({}, interface="virtual", channel="test")
    frame = can.Message(arbitration_id=123, data=b"x", is_extended_id=True)
    await bridge._on_frame(frame)
    await bridge._on_frame(frame)
    assert bridge.state_store.get("a") is True
