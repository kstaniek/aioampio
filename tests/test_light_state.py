"""Regression tests for initial light state from decoded CAN messages."""

from aioampio.models.light import Light


def test_initial_rgb_update_populates_empty_state() -> None:
    """Retain the first color payload before binary channel states arrive."""
    light = Light(id="rgb", on=True, color=True)
    colors = {"red": 10, "green": 20, "blue": 30, "white": 0}
    assert light.update("device.rgb.1", colors)
    assert light.state == colors
    assert not light.update("device.rgb.1", colors)
