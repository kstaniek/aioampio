"""Validate native MLED groups with real controllers and captured CAN writes."""

from copy import deepcopy
from unittest.mock import AsyncMock

import pytest

from aioampio import AmpioBridge
from aioampio.controllers.events import EventType
from aioampio.models.config import Config

PREFIX = "00001e5f_"
SOFA = PREFIX + "light_group_sofa"
KITCHEN = PREFIX + "light_group_kitchen"


def configuration() -> dict:
    """Use the accepted physical output and binary-feedback mappings."""
    return {
        "devices": [
            {
                "can_id": 7775,
                "model": 17,
                "name": "MLED module",
                "lights": [
                    {
                        "id": f"light{i}",
                        "name": f"MLED {i}",
                        "states": [f"aout.{i}", f"binout.{i + 24}"],
                    }
                    for i in range(1, 17)
                ],
                "light_groups": [
                    {
                        "id": "kitchen",
                        "name": "Kitchen",
                        "members": [f"light{i}" for i in range(1, 11)],
                    },
                    {
                        "id": "sofa",
                        "name": "Sofa",
                        "members": [f"light{i}" for i in range(11, 17)],
                    },
                    {
                        "id": "sparse",
                        "name": "Sparse",
                        "members": ["light1", "light16"],
                    },
                ],
            }
        ]
    }


async def make_bridge() -> AmpioBridge:
    """Initialize resources without ever starting a CAN transport."""
    bridge = AmpioBridge(configuration(), interface="virtual", channel="groups")
    await bridge.initialize()
    bridge.send = AsyncMock()
    return bridge


@pytest.mark.parametrize(
    ("group", "value", "payload"),
    [
        (KITCHEN, 255, "00001e5f14ffff03"),
        (KITCHEN, 0, "00001e5f1400ff03"),
        (KITCHEN, 128, "00001e5f1480ff03"),
        (SOFA, 255, "00001e5f14ff00fc"),
        (SOFA, 0, "00001e5f140000fc"),
        (SOFA, 128, "00001e5f148000fc"),
        (PREFIX + "light_group_sparse", 64, "00001e5f14400180"),
    ],
)
async def test_one_masked_frame(group: str, value: int, payload: str) -> None:
    """Use exact accepted destination, function, level, and little-endian mask."""
    bridge = await make_bridge()
    await bridge.lights.set_state(group, on=bool(value), brightness=value)
    bridge.send.assert_awaited_once_with(0x0F000000, data=bytes.fromhex(payload))
    assert bridge.lights[group].state == {"state": None, "brightness": None}
    assert all(not light.state for light in bridge.lights if not light.members)


async def test_plain_on_off_and_individual_commands() -> None:
    """Group commands bypass suffix parsing and do not change member command paths."""
    bridge = await make_bridge()
    await bridge.lights.set_state(SOFA, on=True)
    await bridge.lights.set_state(SOFA, on=False, brightness=128)
    await bridge.lights.set_state(PREFIX + "light11", on=True, brightness=64)
    assert [call.kwargs["data"].hex() for call in bridge.send.await_args_list] == [
        "00001e5f14ff00fc",
        "00001e5f140000fc",
        "00001e5f15400a00",
    ]
    assert bridge.lights.get_device(SOFA).id == "00001e5f"
    assert len(bridge.lights) == 19


@pytest.mark.parametrize("brightness", [-1, 256, 1.5])
async def test_invalid_brightness_sends_nothing(brightness: int) -> None:
    """Reject values before encoding instead of wrapping a byte."""
    bridge = await make_bridge()
    with pytest.raises(ValueError):
        await bridge.lights.set_state(SOFA, on=True, brightness=brightness)
    bridge.send.assert_not_awaited()


async def test_color_is_rejected() -> None:
    """Masked groups cannot be used as RGBW controllers."""
    bridge = await make_bridge()
    with pytest.raises(ValueError, match="no color"):
        await bridge.lights.set_state(SOFA, color=(1, 2, 3, 4))
    bridge.send.assert_not_awaited()


async def test_feedback_and_overlapping_membership() -> None:
    """Update each member and every containing group without stealing raw topics."""
    bridge = await make_bridge()
    sofa = bridge.lights[SOFA]
    sparse = bridge.lights[PREFIX + "light_group_sparse"]
    seen = []
    bridge.lights.subscribe(
        lambda _event, light: seen.append(light.state.copy()),
        SOFA,
        EventType.RESOURCE_UPDATED,
    )
    await bridge.state_store.set("00001e5f.aout.11", {"value": 64})
    assert sofa.state == {"state": True, "brightness": 64}
    assert bridge.lights[PREFIX + "light11"].state == {"brightness": 64}
    assert bridge.lights._topics["00001e5f.aout.11"] == PREFIX + "light11"
    await bridge.state_store.set("00001e5f.aout.16", {"value": 128})
    assert sofa.state == {"state": True, "brightness": 96}
    assert sparse.state == {"state": True, "brightness": 128}
    await bridge.state_store.set("00001e5f.binout.35", {"state": False})
    assert sofa.state == {"state": True, "brightness": 128}
    await bridge.state_store.set("00001e5f.binout.40", {"state": False})
    assert sofa.state == {"state": None, "brightness": None}
    for i in range(12, 16):
        await bridge.state_store.set(f"00001e5f.binout.{i + 24}", {"state": False})
    assert sofa.state == {"state": False, "brightness": 0}
    seen.clear()
    await bridge.state_store.set("00001e5f.aout.11", {"value": 32})
    assert not seen  # An off member's stale level does not change aggregate state.
    bridge.send.assert_not_awaited()


async def test_binary_on_without_brightness() -> None:
    """Power can be known while the group's representative brightness is unknown."""
    bridge = await make_bridge()
    await bridge.state_store.set("00001e5f.binout.35", {"state": True})
    assert bridge.lights[SOFA].state == {"state": True, "brightness": None}


async def test_deleted_members_are_unknown_and_cannot_be_commanded() -> None:
    """Never silently send a partial mask after a member disappears."""
    bridge = await make_bridge()
    for i in range(11, 17):
        await bridge.state_store.set(f"00001e5f.aout.{i}", {"value": 0})
    assert bridge.lights[SOFA].state["state"] is False
    await bridge.lights._handle_event(
        EventType.RESOURCE_DELETED, {"id": PREFIX + "light11"}
    )
    assert bridge.lights[SOFA].state["state"] is None
    with pytest.raises(ValueError, match="Invalid masked light member"):
        await bridge.lights.set_state(SOFA, on=True)
    bridge.send.assert_not_awaited()


async def test_group_deletion_and_close_release_dependencies() -> None:
    """No deleted group is retained by the member dependency index."""
    bridge = await make_bridge()
    await bridge.lights._handle_event(EventType.RESOURCE_DELETED, {"id": SOFA})
    assert all(SOFA not in groups for groups in bridge.lights._member_groups.values())
    bridge.lights.close()
    assert not bridge.lights._member_groups
    assert not bridge.lights._unsubs
    assert not bridge.lights._topics


async def test_send_failure_is_not_retried_as_members() -> None:
    """Propagate uncertainty with one attempt and unchanged received state."""
    bridge = await make_bridge()
    bridge.send.side_effect = ConnectionError("failed write")
    with pytest.raises(ConnectionError, match="failed write"):
        await bridge.lights.set_state(SOFA, on=True)
    assert bridge.send.await_count == 1
    assert bridge.lights[SOFA].state["state"] is None


@pytest.mark.parametrize(
    "case",
    [
        "empty",
        "duplicate_member",
        "qualified_duplicate",
        "missing",
        "nested",
        "cross_device",
        "model",
        "color",
        "binary_only",
        "zero",
        "seventeen",
        "oversized",
        "no_index",
        "duplicate_output",
        "duplicate_group",
        "collision",
        "duplicate_resource",
        "blank",
        "extra",
    ],
)
def test_configuration_rejects_invalid_masks(case: str) -> None:
    """Fail validation before resource setup and any gateway connection."""
    cfg = configuration()
    device = cfg["devices"][0]
    group = device["light_groups"][1]
    if case == "empty":
        group["members"] = []
    elif case == "duplicate_member":
        group["members"].append("light11")
    elif case == "qualified_duplicate":
        group["members"].append(PREFIX + "LIGHT11")
    elif case == "missing":
        group["members"].append("light99")
    elif case == "nested":
        group["members"].append("light_group_kitchen")
    elif case == "cross_device":
        group["members"].append("00001e5e_light1")
    elif case == "model":
        device["model"] = 12
    elif case == "color":
        device["lights"][10]["states"].append("rgb.1")
    elif case == "binary_only":
        device["lights"][10]["states"] = ["binout.35"]
    elif case in {"zero", "seventeen", "oversized", "no_index"}:
        new_id = {
            "zero": "light0",
            "seventeen": "light17",
            "oversized": "light257",
            "no_index": "ceiling",
        }[case]
        device["lights"][10]["id"] = new_id
        group["members"][0] = new_id
    elif case == "duplicate_output":
        device["lights"].append(
            {"id": "alias11", "name": "Alias", "states": ["aout.11"]}
        )
        group["members"].append("alias11")
    elif case == "duplicate_group":
        duplicate = deepcopy(group)
        duplicate["id"] = " SOFA "
        device["light_groups"].append(duplicate)
    elif case == "collision":
        device["lights"][0]["id"] = "light_group_sofa"
    elif case == "duplicate_resource":
        device["lights"].append(deepcopy(device["lights"][0]))
    elif case == "blank":
        group["id"] = " "
    elif case == "extra":
        group["mask"] = 0xFC00
    with pytest.raises(ValueError):
        Config.model_validate(cfg)


async def test_normalized_members_and_stable_group_identity() -> None:
    """Name and membership edits preserve the group's resource identifier."""
    cfg = configuration()
    cfg["devices"][0]["light_groups"][1].update(
        name="New sofa name", members=[" LIGHT11 ", PREFIX + "LIGHT16"]
    )
    bridge = AmpioBridge(cfg, interface="virtual", channel="groups")
    await bridge.initialize()
    assert bridge.lights[SOFA].members == [PREFIX + "light11", PREFIX + "light16"]
    assert bridge.lights[SOFA].name == "New sofa name"
