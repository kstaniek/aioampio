"""Model for sensor entity."""

from dataclasses import dataclass, field
from typing import Any
import logging

from .base import validate_numeric_value
from .resource import ResourceTypes

logger = logging.getLogger(__name__)


@dataclass
class Sensor:
    """Represents a sensor resource with numeric measurements."""

    id: str
    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    state: float | None = None
    area: str | None = None
    unit_of_measurement: str | None = None
    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.SENSOR

    def __post_init__(self) -> None:
        """Post init to set default unit of measurement based on device class."""
        if self.unit_of_measurement is None and self.device_class is not None:
            self.unit_of_measurement = self._get_default_unit(self.device_class)

    @staticmethod
    def _get_default_unit(device_class: str) -> str | None:
        """Get default unit of measurement for device class."""
        units = {
            "temperature": "°C",
            "humidity": "%",
            "atmospheric_pressure": "hPa",
            "illuminance": "lx",
            "sound_pressure": "dB",
            "aqi": None,
        }
        return units.get(device_class)

    def update(self, topic: str, data: dict[str, Any]) -> bool:  # noqa: ARG002
        """Update sensor state from incoming data.

        Args:
            topic: Message topic (unused but kept for protocol consistency)
            data: Payload data containing 'value' key

        Returns:
            True if state changed, False otherwise
        """
        value = data.get("value")
        if value is None:
            logger.debug("Sensor %s: No 'value' in data", self.id)
            return False

        try:
            new_state = validate_numeric_value(value)

            if self.state == new_state:
                return False

            self.state = new_state
            return True

        except (ValueError, TypeError) as e:
            logger.warning("Sensor %s: Invalid value '%s': %s", self.id, value, e)
            return False
