"""Model for sensor entity."""

from dataclasses import dataclass, field

from .resource import ResourceTypes


@dataclass
class Sensor:
    """Represents a sensor resource."""

    id: str
    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    state: float | None = None
    area: str | None = None
    unit_of_measurement: str | None = None
    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.SENSOR

    def __post_init__(self) -> None:
        """Post init to set default unit of measurement based on device class."""
        if self.unit_of_measurement is None and self.device_class is not None:
            match self.device_class:
                case "temperature":
                    self.unit_of_measurement = "°C"
                case "humidity":
                    self.unit_of_measurement = "%"
                case "atmospheric_pressure":
                    self.unit_of_measurement = "hPa"
                case "illuminance":
                    self.unit_of_measurement = "lx"
                case "sound_pressure":
                    self.unit_of_measurement = "dB"
                case "aqi":
                    self.unit_of_measurement = None
                case _:
                    self.unit_of_measurement = None

    def update(self, _topic: str, data: dict[str, int | float | str]) -> None:
        """Update sensor state from incoming data."""
        value = data.get("value")
        try:
            if value is not None:
                self.state = float(value)
            else:
                self.state = None
        except (TypeError, ValueError):
            self.state = None
