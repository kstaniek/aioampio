"""Heating commands use the captured wire format and reported-state contract."""

import asyncio
from unittest.mock import AsyncMock

import pytest

from aioampio import AmpioBridge, AmpioTransmissionError
from aioampio.models.climate import Climate


async def make_bridge(
    model: int = 22, states: list[str] | None = None, **limits: float
) -> AmpioBridge:
    """Use a custom resource ID to distinguish topic addressing from ID suffixes."""
    bridge = AmpioBridge(
        {
            "devices": [
                {
                    "can_id": 0x1B88,
                    "name": "MRT",
                    "model": model,
                    "climates": [
                        {
                            "id": "living_room99",
                            "name": "Living room",
                            "states": states
                            if states is not None
                            else ["heating.3", "zone.3"],
                            **limits,
                        }
                    ],
                }
            ]
        },
        interface="virtual",
        channel="climate-control-tests",
    )
    await bridge.initialize()
    bridge.send = AsyncMock()
    return bridge


@pytest.mark.parametrize(
    ("temperature", "expected"),
    [
        (22.5, "00001b881302e100"),
        (22, "00001b881302dc00"),
        (21.9, "00001b881302db00"),
        (22.1, "00001b881302dd00"),
        (22.25, "00001b881302df00"),
        (7, "00001b8813024600"),
        (35, "00001b8813025e01"),
    ],
)
async def test_captured_setpoints_and_rounding(
    temperature: float, expected: str
) -> None:
    """Use the configured zone and tenths Celsius without the feedback offset."""
    bridge = await make_bridge()
    resource = bridge.climates["00001b88_living_room99"]
    await bridge.climates.set_temperature(resource.id, temperature)
    bridge.send.assert_awaited_once_with(0x0F000000, data=bytes.fromhex(expected))
    assert resource.target_temperature is None
    assert resource.mode is None


@pytest.mark.parametrize("mode", range(4))
async def test_captured_mode_transactions(mode: int) -> None:
    """Compare each mode to the live-captured checksum and sequence layout."""
    bridge = await make_bridge()
    await bridge.climates.set_mode("00001b88_living_room99", mode)
    assert [c.kwargs["data"].hex() for c in bridge.send.await_args_list] == [
        f"00001b88160002{12 + mode:02x}",
        "00001b8816010802",
        f"00001b88160202{mode:02x}",
    ]
    assert all(c.args[0] == 0x0F000000 for c in bridge.send.await_args_list)


@pytest.mark.parametrize(
    "temperature",
    [True, False, "22", None, float("nan"), float("inf"), -float("inf"), -1, 6.9, 35.1],
)
async def test_invalid_temperature_sends_nothing(temperature: object) -> None:
    """Reject non-numeric, non-finite, negative and out-of-guardrail writes."""
    bridge = await make_bridge()
    with pytest.raises(ValueError):
        await bridge.climates.set_temperature("00001b88_living_room99", temperature)
    bridge.send.assert_not_awaited()


@pytest.mark.parametrize("mode", [True, False, -1, 4, 7, 1.0, "1", None])
async def test_invalid_mode_sends_nothing(mode: object) -> None:
    """Do not expose the unconfirmed off/block operation or coerce mode values."""
    bridge = await make_bridge()
    with pytest.raises(ValueError):
        await bridge.climates.set_mode("00001b88_living_room99", mode)
    bridge.send.assert_not_awaited()


@pytest.mark.parametrize("model", [4, 10, 44])
async def test_other_modules_remain_read_only(model: int) -> None:
    bridge = await make_bridge(model=model)
    assert not bridge.climates.supports_control("00001b88_living_room99")
    with pytest.raises(ValueError):
        await bridge.climates.set_temperature("00001b88_living_room99", 22)
    bridge.send.assert_not_awaited()


@pytest.mark.parametrize(
    "states",
    [
        [],
        ["heating.0"],
        ["heating.17"],
        ["heating.3", "zone.4"],
        ["heating.3", "heating.4"],
    ],
)
async def test_ambiguous_or_invalid_channel_is_read_only(states: list[str]) -> None:
    bridge = await make_bridge(states=states)
    assert not bridge.climates.supports_control("00001b88_living_room99")
    with pytest.raises(ValueError):
        await bridge.climates.set_mode("00001b88_living_room99", 0)
    bridge.send.assert_not_awaited()


async def test_configured_limits_and_request_atomicity() -> None:
    bridge = await make_bridge(min_temperature=18, max_temperature=25)
    for temperature in (17.9, 25.1):
        with pytest.raises(ValueError):
            await bridge.climates.set_temperature("00001b88_living_room99", temperature)
    with pytest.raises(ValueError):
        await bridge.climates.set_state(
            "00001b88_living_room99", temperature=22, mode=4
        )
    bridge.send.assert_not_awaited()
    await bridge.climates.set_state("00001b88_living_room99", temperature=22.5, mode=0)
    assert [c.kwargs["data"].hex() for c in bridge.send.await_args_list] == [
        "00001b881302e100",
        "00001b881600020c",
        "00001b8816010802",
        "00001b8816020200",
    ]


@pytest.mark.parametrize(
    "limits",
    [
        {"min_temperature": -1},
        {"max_temperature": 101},
        {"min_temperature": 25, "max_temperature": 20},
        {"min_temperature": 20, "max_temperature": 20},
        {"min_temperature": 7.05},
        {"max_temperature": float("inf")},
    ],
)
async def test_invalid_configured_limits(limits: dict[str, float]) -> None:
    with pytest.raises(ValueError):
        await make_bridge(**limits)


@pytest.mark.parametrize("failed_frame", [0, 1, 2, 3])
async def test_combined_command_stops_on_transport_failure(failed_frame: int) -> None:
    bridge = await make_bridge()
    bridge.send.side_effect = [None] * failed_frame + [
        AmpioTransmissionError("offline")
    ]
    with pytest.raises(AmpioTransmissionError):
        await bridge.climates.set_state(
            "00001b88_living_room99", temperature=22.5, mode=0
        )
    assert bridge.send.await_count == failed_frame + 1
    assert bridge.climates["00001b88_living_room99"].mode is None


async def test_climate_transactions_do_not_interleave() -> None:
    bridge = await make_bridge()
    entered = asyncio.Event()
    release = asyncio.Event()
    sent = []

    async def send(can_id: int, *, data: bytes) -> None:
        sent.append(data.hex())
        if len(sent) == 1:
            entered.set()
            await release.wait()

    bridge.send.side_effect = send
    mode = asyncio.create_task(bridge.climates.set_mode("00001b88_living_room99", 1))
    await asyncio.wait_for(entered.wait(), timeout=1)
    target = asyncio.create_task(
        bridge.climates.set_temperature("00001b88_living_room99", 22.5)
    )
    try:
        await asyncio.sleep(0)
        assert len(sent) == 1
    finally:
        release.set()
        await asyncio.gather(mode, target)
    assert sent == [
        "00001b881600020d",
        "00001b8816010802",
        "00001b8816020201",
        "00001b881302e100",
    ]


def test_mode_feedback_unknown_and_invalid_values() -> None:
    resource = Climate(id="zone")
    assert resource.mode is None
    assert resource.update("d.heating.3", {"operating_mode": 0})
    assert not resource.update("d.heating.3", {"operating_mode": 0})
    assert resource.update("d.heating.3", {"operating_mode": 4})
    for value in (False, "1", 1.5, -1, 8, None):
        assert not resource.update("d.heating.3", {"operating_mode": value})
        assert resource.mode == 4
