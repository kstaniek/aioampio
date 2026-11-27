"""Validate light-group member defaults without removing feedback resources."""

from unittest.mock import AsyncMock

import pytest

from aioampio import AmpioBridge
from aioampio.models.config import Config

from test_light_groups import PREFIX, SOFA, configuration


@pytest.mark.parametrize("option", ["members_enabled", "members_visible"])
@pytest.mark.parametrize("enabled", [None, True, False])
async def test_member_options_round_trip(option: str, enabled: bool | None) -> None:
    """Preserve the explicit default and keep every member available to the library."""
    cfg = configuration()
    group = cfg["devices"][0]["light_groups"][1]
    if enabled is not None:
        group[option] = enabled
    validated = Config.model_validate(cfg)
    expected = enabled is not False
    assert getattr(validated.devices[0].light_groups[1], option) is expected
    bridge = AmpioBridge(cfg, interface="virtual", channel="group-options")
    await bridge.initialize()
    bridge.send = AsyncMock()
    assert getattr(bridge.lights[SOFA], option) is expected
    assert getattr(bridge.lights[PREFIX + "light_group_sparse"], option) is True
    assert len(bridge.lights) == 19
    await bridge.state_store.set("00001e5f.aout.11", {"value": 64})
    assert bridge.lights[PREFIX + "light11"].state["brightness"] == 64
    assert bridge.lights[SOFA].state == {"state": True, "brightness": 64}
    bridge.send.assert_not_awaited()


@pytest.mark.parametrize("option", ["members_enabled", "members_visible"])
@pytest.mark.parametrize("invalid", [None, "false", "true", 0, 1, [], {}])
def test_member_options_require_boolean(option: str, invalid: object) -> None:
    """Reject ambiguous values before connecting or creating any resources."""
    cfg = configuration()
    cfg["devices"][0]["light_groups"][1][option] = invalid
    with pytest.raises(ValueError, match=option):
        Config.model_validate(cfg)
