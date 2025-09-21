# tests/test_codec_contract.py
from __future__ import annotations

import sys
import importlib
from typing import Iterable, List, Protocol

import pytest

from aioampio.codec.base import CANFrame
from aioampio.codec.registry import registry


class _CodecProto(Protocol):
    def decode(self, frame: CANFrame) -> Iterable[object]: ...


@pytest.fixture(autouse=True)
def _isolate_registry():
    """Snapshot and restore codec registry to keep tests hermetic."""
    reg = registry()
    original = list(getattr(reg, "_codecs", []))
    try:
        # start each test with a clean registry
        reg._codecs = []  # type: ignore[attr-defined]
        yield
    finally:
        reg._codecs = original  # type: ignore[attr-defined]


def _register_fake(codec: _CodecProto) -> None:
    registry().register(codec)  # type: ignore[arg-type]


def test_ampio_codec_registers_on_import():
    # clear any previous import so module body (registration) runs again
    sys.modules.pop("aioampio.codec.ampio", None)
    importlib.import_module("aioampio.codec.ampio")

    reg = registry()
    assert len(getattr(reg, "_codecs", [])) >= 1


def test_decode_no_codecs_returns_empty_list():
    frame = CANFrame(can_id=0x12345678, data=memoryview(b"\x00" * 8))
    out = registry().decode(frame)
    assert isinstance(out, list)
    assert out == []


def test_registry_dispatch_to_matching_codec():
    calls: list[int] = []

    class OnlyIdCodec:
        def __init__(self, match_id: int) -> None:
            self.match_id = match_id

        def decode(self, frame: CANFrame) -> List[object]:
            calls.append(frame.can_id)
            if frame.can_id == self.match_id:
                return [{"decoded": True, "id": frame.can_id}]
            return []

    target_id = 0xDEADBEEF
    _register_fake(OnlyIdCodec(match_id=target_id))

    # non-matching
    out1 = registry().decode(CANFrame(can_id=0xABCDEF01, data=memoryview(b"\x00")))
    assert out1 == []

    # matching
    out2 = registry().decode(CANFrame(can_id=target_id, data=memoryview(b"\x01\x02")))
    assert out2 == [{"decoded": True, "id": target_id}]
    assert calls == [0xABCDEF01, target_id]


def test_registry_short_circuits_on_first_match():
    order: list[str] = []

    class FirstCodec:
        def decode(self, frame: CANFrame):
            order.append("first")
            return [{"by": "first"}]  # always matches

    class SecondCodec:
        def decode(self, frame: CANFrame):
            order.append("second")
            # if this is called, the registry didn't short-circuit
            return [{"by": "second"}]

    _register_fake(FirstCodec())
    _register_fake(SecondCodec())

    out = registry().decode(CANFrame(can_id=0x111, data=memoryview(b"\x00")))
    assert out == [{"by": "first"}]
    assert order == ["first"]  # ensure second wasn't consulted


def test_decoder_accepts_memoryview_zero_copy():
    seen = {}

    class EchoCodec:
        def decode(self, frame: CANFrame):
            # capture exactly what we received
            seen["is_mv"] = isinstance(frame.data, memoryview)
            seen["bytes"] = frame.data.tobytes()
            return [{"len": len(frame.data)}]

    _register_fake(EchoCodec())

    payload = b"\x10\x20\x30\x40"
    mv = memoryview(payload)
    out = registry().decode(CANFrame(can_id=0x222, data=mv))

    assert out == [{"len": 4}]
    assert seen["is_mv"] is True
    assert seen["bytes"] == payload


def test_fake_codec_dlc_guard_yields_empty():
    """A codec can choose to ignore frames with unexpected DLC without raising."""

    class Dlc8Codec:
        def decode(self, frame: CANFrame):
            if len(frame.data) != 8:
                return []
            return [{"ok": True}]

    _register_fake(Dlc8Codec())

    out_bad = registry().decode(CANFrame(can_id=0x333, data=memoryview(b"\x00" * 7)))
    out_ok = registry().decode(CANFrame(can_id=0x333, data=memoryview(b"\x00" * 8)))

    assert out_bad == []
    assert out_ok == [{"ok": True}]
