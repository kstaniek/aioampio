"""Regression tests for defaults used when creating configured resources."""

from typing import Any

import pytest

from aioampio import AmpioBridge


@pytest.mark.parametrize(
    ("platform", "states", "overrides", "expected"),
    [
        pytest.param("lights", ["aout.1"], {}, False, id="dimmable-default"),
        pytest.param("lights", ["rgb.1"], {}, False, id="rgb-default"),
        pytest.param("lights", ["binout.1"], {}, True, id="binary-derived"),
        pytest.param("lights", ["aout.1"], {"on": True}, True, id="light-explicit-on"),
        pytest.param(
            "lights", ["aout.1"], {"on": False}, False, id="light-explicit-off"
        ),
        pytest.param("switches", ["binout.1"], {}, False, id="switch-default"),
        pytest.param(
            "switches", ["binout.1"], {"on": True}, True, id="switch-explicit-on"
        ),
        pytest.param(
            "switches", ["binout.1"], {"on": False}, False, id="switch-explicit-off"
        ),
    ],
)
async def test_resource_defaults(
    platform: str,
    states: list[str],
    overrides: dict[str, Any],
    expected: bool,
) -> None:
    """Load omitted and explicit capability values through all controllers."""
    config = {
        "devices": [
            {
                "can_id": 0x123,
                "name": "Test relay",
                "model": 4,
                platform: [
                    {
                        "id": "output1",
                        "name": "Test output",
                        "states": states,
                        **overrides,
                    }
                ],
            }
        ]
    }
    bridge = AmpioBridge(config, interface="virtual", channel="config-test")
    try:
        await bridge.initialize()
        controller = getattr(bridge, platform)
        resource = controller["00000123_output1"]
        assert resource.on is expected
        assert resource.owner == "00000123"
        assert resource.states == states
    finally:
        await bridge.stop()
