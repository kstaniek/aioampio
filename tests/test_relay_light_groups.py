"""Exercise the physically verified MREL8S mask without opening a transport."""

from unittest.mock import AsyncMock

import pytest

from aioampio import AmpioBridge
from aioampio.models.config import Config

PREFIX = "00001a1e_"
GARAGE = PREFIX + "light_group_garaz"


def configuration() -> dict:
    """Keep physical output numbers distinct from binary feedback offsets."""
    return {
        "devices": [
            {
                "can_id": 6686,
                "name": "Relay module",
                "model": 4,
                "lights": [
                    {
                        "id": f"light{i}",
                        "name": f"Relay {i}",
                        "states": [f"binout.{i + 24}"],
                    }
                    for i in range(1, 9)
                ],
                "light_groups": [
                    {
                        "id": "garaz",
                        "name": "Garaż",
                        "area": "Garaż",
                        "members": ["light3", "light5", "light6"],
                    }
                ],
            }
        ]
    }


async def make_bridge(cfg: dict | None = None) -> AmpioBridge:
    """Initialize only resources and intercept every outbound frame."""
    bridge = AmpioBridge(
        cfg or configuration(), interface="virtual", channel="relay-groups"
    )
    await bridge.initialize()
    bridge.send = AsyncMock()
    return bridge


@pytest.mark.parametrize(
    ("command", "payload"),
    [
        ({"on": True}, "00001a1e14ff3400"),
        ({"on": False}, "00001a1e14003400"),
        ({"brightness": 255}, "00001a1e14ff3400"),
        ({"brightness": 0}, "00001a1e14003400"),
    ],
)
async def test_garage_exact_frame(command: dict, payload: str) -> None:
    """Reproduce both accepted frames with no individual fan-out or optimistic state."""
    bridge = await make_bridge()
    await bridge.lights.set_state(GARAGE, **command)
    bridge.send.assert_awaited_once_with(0x0F000000, data=bytes.fromhex(payload))
    group = bridge.lights[GARAGE]
    assert len(bridge.lights) == 9
    assert not group.supports_dimming
    assert not group.supports_color
    assert group.state == {"state": None, "brightness": None}
    assert all(not light.state for light in bridge.lights if not light.members)


@pytest.mark.parametrize("level", [-1, 1, 128, 254, 256, 1.5])
async def test_relay_rejects_brightness(level: int) -> None:
    """No unsupported relay dimming request reaches CAN."""
    bridge = await make_bridge()
    with pytest.raises(ValueError):
        await bridge.lights.set_state(GARAGE, on=True, brightness=level)
    bridge.send.assert_not_awaited()


async def test_individual_feedback_updates_group() -> None:
    """Track unknown, any on and all off without inventing a brightness level."""
    bridge = await make_bridge()
    group = bridge.lights[GARAGE]
    await bridge.state_store.set("00001a1e.binout.27", {"state": False})
    assert group.is_on is None
    await bridge.state_store.set("00001a1e.binout.29", {"state": True})
    assert group.is_on is True
    await bridge.state_store.set("00001a1e.binout.30", {"state": False})
    await bridge.state_store.set("00001a1e.binout.29", {"state": False})
    assert group.state == {"state": False, "brightness": None}
    await bridge.state_store.set("00001a1e.binout.28", {"state": True})
    assert group.is_on is False  # Unselected relay cannot change the group.
    await bridge.state_store.set("00001a1e.binout.30", {"state": True})
    assert group.state == {"state": True, "brightness": None}
    assert bridge.lights[PREFIX + "light6"].is_on is True
    bridge.send.assert_not_awaited()


async def test_eighth_output_and_indexed_individual_command() -> None:
    """Use eight physical outputs, not the binout.25..32 feedback indices."""
    cfg = configuration()
    cfg["devices"][0]["light_groups"][0]["members"] = ["light8"]
    bridge = await make_bridge(cfg)
    await bridge.lights.set_state(GARAGE, on=True)
    await bridge.lights.set_state(PREFIX + "light3", on=True)
    assert [call.kwargs["data"].hex() for call in bridge.send.await_args_list] == [
        "00001a1e14ff8000",
        "00001a1e15ff0200",
    ]


@pytest.mark.parametrize(
    "case", ["ninth", "dimmable", "color", "no_power", "other_model"]
)
def test_relay_configuration_rejects_unsupported_members(case: str) -> None:
    """Restrict support to verified binary relay outputs and models."""
    cfg = configuration()
    device = cfg["devices"][0]
    member = device["lights"][2]
    if case == "ninth":
        member["id"] = "light9"
        device["light_groups"][0]["members"][0] = "light9"
    elif case == "dimmable":
        member["states"].append("aout.3")
    elif case == "color":
        member["states"].append("rgb.3")
    elif case == "no_power":
        member["states"] = ["s16b.3"]
    else:
        device["model"] = 22
    with pytest.raises(ValueError):
        Config.model_validate(cfg)


async def test_runtime_member_validation_and_send_failure() -> None:
    """Revalidate mutable resources and retain a single attempt on transport failure."""
    bridge = await make_bridge()
    member = bridge.lights[PREFIX + "light3"]
    member.dimming = True
    with pytest.raises(ValueError, match="Invalid masked light member"):
        await bridge.lights.set_state(GARAGE, on=True)
    bridge.send.assert_not_awaited()
    member.dimming = False
    bridge.send.side_effect = ConnectionError("failed write")
    with pytest.raises(ConnectionError, match="failed write"):
        await bridge.lights.set_state(GARAGE, on=True)
    assert bridge.send.await_count == 1
    assert bridge.lights[GARAGE].is_on is None
