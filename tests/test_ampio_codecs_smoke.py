# tests/test_ampio_codecs_smoke.py
from __future__ import annotations

import importlib
import sys
import itertools
import random
from collections.abc import Iterable
from typing import Callable, Any

import pytest

from aioampio.codec.base import CANFrame
from aioampio.codec.registry import registry


def _reload_ampio_codec_module() -> None:
    """Ensure the ampio codec module re-executes to (re)register decoders."""
    sys.modules.pop("aioampio.codec.ampio", None)
    importlib.import_module("aioampio.codec.ampio")


@pytest.fixture(scope="module")
def codecs():
    _reload_ampio_codec_module()
    reg = registry()
    codecs = getattr(reg, "_codecs", [])
    # sanity: at least one codec should be present
    assert isinstance(codecs, list)
    assert len(codecs) >= 1
    return codecs


def _mv(data: bytes) -> memoryview:
    return memoryview(data)


@pytest.mark.parametrize("dlc", range(0, 9))  # DLC 0..8 (classic CAN)
def test_each_codec_handles_all_dlcs_without_exceptions(codecs, dlc: int):
    """Every registered codec must accept all classic CAN DLCs and never raise."""
    buf = bytes([0x00] * dlc)
    frame = CANFrame(can_id=0x12345678, data=_mv(buf))  # id likely non-matching

    for codec in codecs:
        before = bytes(frame.data)
        out = codec.decode(frame)
        after = bytes(frame.data)

        # A decoder may return None for non-match; it must not raise or mutate data
        assert (out is None) or isinstance(out, Iterable)
        assert before == after


def test_each_codec_nonmatching_returns_iterable_or_none(codecs):
    """For random non-matching ids, decode should not raise and may return None or an iterable."""
    random.seed(1337)
    rand_ids = [random.randint(0, 0x1FFFFFFF) for _ in range(5)]
    payloads = [b"", b"\x00", b"\xff" * 8]

    for codec in codecs:
        for can_id, data in itertools.product(rand_ids, payloads):
            frame = CANFrame(can_id=can_id, data=_mv(data))
            out = codec.decode(frame)
            assert (out is None) or isinstance(out, Iterable)


def test_registry_decode_always_returns_list(codecs):
    """registry().decode must always return a list (possibly empty)."""
    from aioampio.codec.registry import registry as get_registry

    for dlc in range(0, 9):
        frame = CANFrame(can_id=0x01020304, data=_mv(bytes([0xAA] * dlc)))
        out = get_registry().decode(frame)
        assert isinstance(out, list)


# ------------------------------------------------------------------------------
# Optional: targeted vectors per codec (fill when you know specifics).
# ------------------------------------------------------------------------------


def _hex(s: str) -> bytes:
    s = s.replace(" ", "").replace("_", "")
    return bytes.fromhex(s)


# Example structure for when you add specific assertions later:
# def _expect_first_item_has_field(out: list):
#     assert out and isinstance(out[0], dict)
#     assert out[0].get("field") == 0x0102
#
# KNOWN_VECTORS: dict[
#     str | Callable[[Any], bool],
#     list[tuple[int, str, Callable[[list], None]]],
# ] = {
#     "SomeCodecClassName": [
#         (0x18FF1234, "01 02 03 04 05 06 07 08", _expect_first_item_has_field),
#     ],
# }


def _expect_no_output(out: list):
    assert out == []


def _expect_ampio_temperature_sensor(out: list):
    assert out and len(out) == 1
    msg = out[0]
    assert hasattr(msg, "topic")
    assert msg.topic.startswith("00000001.temperature.1")
    assert hasattr(msg, "payload")
    assert isinstance(msg.payload, dict)
    assert "value" in msg.payload
    assert isinstance(msg.payload["value"], (int, float))
    assert msg.payload["value"] == 24.1
    assert "unit" in msg.payload
    assert msg.payload["unit"] == "°C"


def _expect_sb16b1000(base_index: int, length: int) -> Callable[[list], None]:
    values = (54, 983.3, 40.4)

    def _expect(out: list):
        assert out and len(out) == length
        for i, msg in enumerate(out):
            assert hasattr(msg, "topic")
            assert msg.topic.startswith(f"00000001.s16b10000.{i + base_index}")
            assert hasattr(msg, "payload")
            payload = msg.payload
            assert isinstance(payload, dict)
            assert "value" in payload
            val = payload["value"]
            assert isinstance(val, (int, float))
            assert val == values[i]

    return _expect


def _expect_u8b(base_index: int, length: int) -> Callable[[list], None]:
    values = (1, 2, 3, 16, 17, 18)

    def _expect(out: list):
        assert len(out) == length
        for i, msg in enumerate(out):
            assert hasattr(msg, "topic")
            assert msg.topic.startswith(f"00000001.aout.{i + base_index}")
            assert hasattr(msg, "payload")
            payload = msg.payload
            assert isinstance(payload, dict)
            assert "value" in payload
            val = payload["value"]
            assert isinstance(val, (int, float))
            assert val == values[i]

    return _expect


def _expect_binout(base_index: int, length: int) -> Callable[[list], None]:
    states = (
        [True] * 8 + [False] * 8 + [True] * 8 + [False] * 8 + [True] * 8 + [False] * 8
    )

    def _expect(out: list):
        assert len(out) == length
        for i, msg in enumerate(out):
            assert hasattr(msg, "topic")
            assert msg.topic.startswith(f"00000001.binout.{i + base_index}")
            assert hasattr(msg, "payload")
            payload = msg.payload
            assert isinstance(payload, dict)
            assert "state" in payload
            state = payload["state"]
            assert isinstance(state, bool)
            assert state == states[i]

    return _expect


def _expect_date_time(out: list):
    assert out and len(out) == 1
    msg = out[0]
    assert hasattr(msg, "topic")
    assert msg.topic.startswith("00000001.datetime.1")
    assert hasattr(msg, "payload")
    assert isinstance(msg.payload, dict)
    assert "year" in msg.payload
    assert msg.payload["year"] == 2025
    assert "month" in msg.payload
    assert msg.payload["month"] == 9
    assert "day" in msg.payload
    assert "daytime" in msg.payload
    assert msg.payload["daytime"] == 0
    assert "hour" in msg.payload
    assert msg.payload["hour"] == 13
    assert "minute" in msg.payload
    assert msg.payload["minute"] == 1
    assert "weekday" in msg.payload
    assert msg.payload["weekday"] == 7


def _expected_satel_armed(
    base_index: int, length: int, entity: str
) -> Callable[[list], None]:
    states = [False] * 4 + [True] * 4

    def _expect(out: list):
        assert len(out) == length
        for i, msg in enumerate(out):
            assert hasattr(msg, "topic")
            assert msg.topic.startswith(f"00000001.{entity}.{i + base_index}")
            assert hasattr(msg, "payload")
            payload = msg.payload
            assert isinstance(payload, dict)
            assert "state" in payload
            state = payload["state"]
            assert isinstance(state, bool)
            assert state == states[i]

    return _expect


def _expected_satel_binout(
    base_index: int, length: int, entity: str
) -> Callable[[list], None]:
    trues = [17, 31, 33, 35, 42, 44, 45, 47]

    def _expect(out: list):
        assert len(out) == length
        for i, msg in enumerate(out):
            assert hasattr(msg, "topic")
            assert msg.topic.startswith(f"00000001.{entity}.{i + base_index}")
            assert hasattr(msg, "payload")
            payload = msg.payload
            assert isinstance(payload, dict)
            assert "state" in payload
            state = payload["state"]
            assert isinstance(state, bool)
            assert state == (True if i + 1 in trues else False)

    return _expect


def _expected_heating_zone(base_index: int) -> Callable[[list], None]:
    def _expect(out: list):
        assert out and len(out) == 1
        msg = out[0]
        assert hasattr(msg, "topic")
        assert msg.topic.startswith(f"00000001.heating.{base_index}")
        assert hasattr(msg, "payload")
        assert isinstance(msg.payload, dict)
        assert "active" in msg.payload
        assert msg.payload["active"]
        assert "current_temperature" in msg.payload
        assert msg.payload["current_temperature"] == 22.5
        assert "target_temperature" in msg.payload
        assert msg.payload["target_temperature"] == 17.6
        assert "temperature_diff" in msg.payload
        assert msg.payload["temperature_diff"] == -4.9
        assert "day_mode" in msg.payload
        assert msg.payload["day_mode"]
        assert "heating" in msg.payload
        assert not msg.payload["heating"]
        assert "mode" in msg.payload
        assert msg.payload["mode"] == 0

    return _expect


def _expect_rgb(out: list):
    assert out and len(out) == 1
    msg = out[0]
    assert hasattr(msg, "topic")
    assert msg.topic.startswith("00000001.rgb.1")
    assert hasattr(msg, "payload")
    assert isinstance(msg.payload, dict)
    assert "red" in msg.payload
    assert msg.payload["red"] == 7
    assert "green" in msg.payload
    assert msg.payload["green"] == 8
    assert "blue" in msg.payload
    assert msg.payload["blue"] == 9
    assert "white" in msg.payload
    assert msg.payload["white"] == 10


def _expect_satel_status(out: list):
    assert out and len(out) == 1
    msg = out[0]
    assert hasattr(msg, "topic")
    assert msg.topic.startswith("00000001.response.1")
    assert hasattr(msg, "payload")
    assert isinstance(msg.payload, dict)
    assert "status" in msg.payload
    assert msg.payload["status"] == 7
    assert "response" in msg.payload
    assert msg.payload["response"] == "changed code is the same"


def _expect_diagnostics(out: list):
    assert out and len(out) == 1
    msg = out[0]
    assert hasattr(msg, "topic")
    assert msg.topic.startswith("00000001.diagnostics.1")
    assert hasattr(msg, "payload")
    assert isinstance(msg.payload, dict)
    assert "temperature" in msg.payload
    assert msg.payload["temperature"] == 30
    assert "voltage" in msg.payload
    assert msg.payload["voltage"] == 11.4


def _expect_s16b(base_index: int, length: int) -> Callable[[list], None]:
    values = (44, 982, 114)  # if this is a temp / 10

    def _expect(out: list):
        assert out and len(out) == length
        for i, msg in enumerate(out):
            assert hasattr(msg, "topic")
            assert msg.topic.startswith(f"00000001.s16b.{i + base_index}")
            assert hasattr(msg, "payload")
            payload = msg.payload
            assert isinstance(payload, dict)
            assert "value" in payload
            print(payload)
            val = payload["value"]
            assert isinstance(val, (int, float))
            assert val == values[i]

    return _expect


KNOWN_VECTORS: dict[
    str | Callable[[Any], bool],
    list[tuple[int, str, Callable[[list], None]]],
] = {
    "AmpioCodec": [
        (0x00000001, "FE 06 D9 04 B5 04 00 00", _expect_ampio_temperature_sensor),
        (0x00000001, "FE 21 2C 29 79 4D A4 28", _expect_sb16b1000(1, 3)),
        (0x00000001, "FE 22 2C 29 79 4D A4 28", _expect_sb16b1000(4, 3)),
        (0x00000001, "FE 23 2C 29 79 4D A4 28", _expect_sb16b1000(7, 3)),
        (0x00000001, "FE 24 2C 29 79 4D A4 28", _expect_sb16b1000(10, 3)),
        (0x00000001, "FE 25 2C 29 79 4D A4 28", _expect_sb16b1000(13, 3)),
        (0x00000001, "FE 23 2C 29", _expect_sb16b1000(7, 1)),
        (0x00000001, "FE 23 2C", _expect_no_output),
        (0x00000001, "FE 0C 01 02 03 10 11 12", _expect_u8b(1, 6)),
        (0x00000001, "FE 0C 01 02 03 10 11", _expect_u8b(1, 5)),
        (0x00000001, "FE 0C 01", _expect_u8b(1, 1)),
        (0x00000001, "FE 0C", _expect_u8b(1, 0)),
        (0x00000001, "FE 0D 01 02 03 10 11 12", _expect_u8b(7, 6)),
        (0x00000001, "FE 0E 01 02 03 10 11 12", _expect_u8b(13, 6)),
        (0x00000001, "FE 0F FF 00 FF 00 FF 00", _expect_binout(1, 48)),
        (0x00000001, "FE 10 19 09 15 07 0D 01", _expect_date_time),
        (0x00000001, "FE 10 19 09 15 07 0D", _expect_no_output),
        # not supported yet index 4 value 2452
        # fe_18_00_00_97_09_00_00 -> index 1 value 2455
        # 209e (Modbus)
        (0x00000001, "FE 18 00 03 94 90 00 00", _expect_no_output),
        (0x00000001, "FE 19 F0 00 FF 00 FF 00", _expected_satel_armed(1, 8, "armed")),
        (0x00000001, "FE 1A F0 00 FF 00 FF 00", _expected_satel_armed(1, 8, "alarm")),
        (
            0x00000001,
            "FE 38 F0 00 FF 00 FF 00",
            _expected_satel_armed(1, 8, "breached"),
        ),
        (0x00000001, "FE 39 F0 00 FF 00 FF 00", _expected_satel_armed(1, 8, "arming")),
        (
            0x00000001,
            "FE 3A F0 00 FF 00 FF 00",
            _expected_satel_armed(1, 8, "arming_10s"),
        ),
        (0x00000001, "FE 1B 00 00 01 40 05 5A", _expected_satel_binout(1, 48, "bin")),
        (0x00000001, "FE 1C 00 00 01 40 05 5A", _expected_satel_binout(49, 48, "bin")),
        (0x00000001, "FE 1D 00 00 01 40 05 5A", _expected_satel_binout(97, 48, "bin")),
        (0x00000001, "FE 1E 00 00 01 40 05 5A", _expected_satel_binout(1, 48, "bout")),
        (0x00000001, "FE 1F 00 00 01 40 05 5A", _expected_satel_binout(49, 48, "bout")),
        (0x00000001, "FE 20 00 00 01 40 05 5A", _expected_satel_binout(97, 48, "bout")),
        (0x00000001, "FE 80 00 00 01 40 05 5A", _expected_satel_binout(1, 32, "flag")),
        (0x00000001, "FE C8 00 00 01 40 05 5A", _expected_satel_binout(1, 16, "zone")),
        (0x00000001, "FE C9 E1 04 B0 04 33 05", _expected_heating_zone(1)),
        (0x00000001, "FE CA E1 04 B0 04 33 05", _expected_heating_zone(2)),
        (0x00000001, "FE CB E1 04 B0 04 33 05", _expected_heating_zone(3)),
        (0x00000001, "FE CC E1 04 B0 04 33 05", _expected_heating_zone(4)),
        (0x00000001, "FE CD E1 04 B0 04 33 05", _expected_heating_zone(5)),
        (0x00000001, "FE CE E1 04 B0 04 33 05", _expected_heating_zone(6)),
        (0x00000001, "FE CF E1 04 B0 04 33 05", _expected_heating_zone(7)),
        (0x00000001, "FE D0 E1 04 B0 04 33 05", _expected_heating_zone(8)),
        (0x00000001, "FE D1 E1 04 B0 04 33 05", _expected_heating_zone(9)),
        (0x00000001, "FE D2 E1 04 B0 04 33 05", _expected_heating_zone(10)),
        (0x00000001, "FE D3 E1 04 B0 04 33 05", _expected_heating_zone(11)),
        (0x00000001, "FE D4 E1 04 B0 04 33 05", _expected_heating_zone(12)),
        (0x00000001, "FE D5 E1 04 B0 04 33 05", _expected_heating_zone(13)),
        (0x00000001, "FE D6 E1 04 B0 04 33 05", _expected_heating_zone(14)),
        (0x00000001, "FE D7 E1 04 B0 04 33 05", _expected_heating_zone(15)),
        (0x00000001, "FE D8 E1 04 B0 04 33 05", _expected_heating_zone(16)),
        (0x00000001, "FE 49 07 08 09 0A", _expect_rgb),
        (0x00000001, "10 EF 07", _expect_satel_status),
        (0x00000001, "FE 4F 39 82", _expect_diagnostics),
        (0x00000001, "FE 44 39", _expect_no_output),
        (0x00000001, "FE 44 2C 00 D6 03 72 00", _expect_s16b(1, 3)),
    ],
}


def _matches_codec(codec: Any, key: str | Callable[[Any], bool]) -> bool:
    if callable(key):
        return bool(key(codec))
    return codec.__class__.__name__ == key


@pytest.mark.parametrize("selector", list(KNOWN_VECTORS.keys()))
def test_known_vectors_for_specific_codecs(codecs, selector):
    selected = [c for c in codecs if _matches_codec(c, selector)]
    if not selected:
        pytest.skip(f"No codec matched selector {selector!r}")
    codec = selected[0]

    for can_id, hex_data, predicate in KNOWN_VECTORS[selector]:
        frame = CANFrame(can_id=can_id, data=_mv(_hex(hex_data)))
        out = codec.decode(frame)
        out = [] if out is None else (list(out) if not isinstance(out, list) else out)
        predicate(out)
