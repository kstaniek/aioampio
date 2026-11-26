"""Exercise model state transitions and invalid decoded values."""

import pytest

from aioampio.models.alarm_control_panel import AlarmControlPanel
from aioampio.models.binary_sensor import BinarySensor
from aioampio.models.climate import Climate
from aioampio.models.cover import Cover, CoverState
from aioampio.models.light import Light
from aioampio.models.sensor import Sensor
from aioampio.models.switch import Switch
from aioampio.models.text import Text
from aioampio.models.valve import Valve


@pytest.mark.parametrize("model", [BinarySensor(id="b"), Switch(id="s", on=True)])
def test_binary_changes_and_missing_fields(model: BinarySensor | Switch) -> None:
    """Missing state does not invent a reading, and duplicate values are ignored."""
    assert model.state is None
    assert not model.update("d.binin.1", {})
    assert model.update("d.binin.1", {"state": True})
    assert model.state is True
    assert not model.update("d.binin.1", {"state": True})
    assert model.update("d.binin.1", {"state": False})
    assert model.state is False


@pytest.mark.parametrize(
    "invalid", [float("nan"), float("inf"), -float("inf"), "not-numeric"]
)
def test_sensor_rejects_invalid_readings(invalid: object) -> None:
    """Do not replace the last usable sensor state with an invalid number."""
    sensor = Sensor(id="s", device_class="temperature")
    assert sensor.unit_of_measurement == "°C"
    assert sensor.update("d.temperature.1", {"value": "21.5"})
    assert not sensor.update("d.temperature.1", {"value": invalid})
    assert sensor.state == 21.5


def test_climate_updates_independent_fields() -> None:
    """An invalid temperature must not discard valid accompanying status fields."""
    climate = Climate(id="c")
    assert climate.update(
        "d.climate.1",
        {
            "current_temperature": 20,
            "target_temperature": 22,
            "heating": True,
            "state": True,
        },
    )
    assert not climate.update(
        "d.climate.1",
        {
            "current_temperature": 20,
            "target_temperature": 22,
            "heating": True,
            "state": True,
        },
    )
    assert climate.update(
        "d.climate.1", {"current_temperature": float("nan"), "heating": False}
    )
    assert climate.current_temperature == 20
    assert climate.target_temperature == 22
    assert climate.heating is False


@pytest.mark.parametrize("model", [Cover(id="c"), Valve(id="v")])
def test_motor_direction_and_position(model: Cover | Valve) -> None:
    """Follow opening, stop, position, and closing events without resetting position."""
    assert model.update("d.aout.1", {"value": 50})
    assert model.state == "open"
    assert model.update("d.binout.2", {"state": True})
    assert model.state == "opening"
    assert model.update("d.binout.2", {"state": False})
    assert model.state == "open"
    assert model.update("d.binout.1", {"state": True})
    assert model.state == "closing"
    assert model.update("d.binout.1", {"state": False})
    assert model.update("d.aout.1", {"value": 0})
    assert model.state == "closed"


@pytest.mark.parametrize("factory", [Cover, Valve])
@pytest.mark.parametrize("value", [-1, 101, None, float("nan"), float("inf")])
def test_bad_position_preserves_unknown_state(factory: type, value: object) -> None:
    """Invalid data is not evidence that a cover or valve is closed."""
    model = factory(id="motor")
    assert not model.update("d.aout.1", {"value": value})
    assert model.state == "unknown"


def test_cover_tilt_and_irrelevant_topic() -> None:
    """Use the tilt index range and ignore unrelated data."""
    cover = Cover(id="c")
    assert not cover.update("d.aout.99", {"value": 50})
    assert cover.state == CoverState.UNKNOWN
    assert cover.update("d.aout.7", {"value": 30})
    assert cover.tilt.position == 30
    assert cover.cover.position == 0
    assert cover.state == CoverState.OPEN


def test_alarm_flags_and_unknown_topics() -> None:
    """Retain unknown flags until a recognized state topic arrives."""
    alarm = AlarmControlPanel(id="a")
    assert all(value is None for value in alarm.get_state().values())
    assert not alarm.update("invalid", {"state": True})
    assert not alarm.update("d.invalid.1", {"state": True})
    assert alarm.update("d.armed.1", {"state": True})
    assert not alarm.update("d.armed.1", {"state": True})
    assert alarm.get_state()["armed"] is True
    assert alarm.get_state()["alarm"] is None


def test_text_updates_and_clear() -> None:
    """Text updates can be deduplicated and explicitly cleared."""
    text = Text(id="t")
    assert not text.update("d.text.1", {})
    assert text.update("d.text.1", {"response": "ready"})
    assert not text.update("d.text.1", {"response": "ready"})
    assert text.update("d.text.1", {"response": None})
    assert text.state is None


def test_brightness_remains_a_byte_for_command_roundtrip() -> None:
    """Received brightness must remain usable by byte-oriented command encoders."""
    light = Light(id="dimmer", on=False, dimming=True)
    assert light.update("d.aout.1", {"value": 128})
    brightness = light.state["brightness"]
    assert type(brightness) is int
    assert bytes([brightness]) == b"\x80"
    assert not light.update("d.aout.1", {"value": 12.5})
    assert light.state["brightness"] == 128
