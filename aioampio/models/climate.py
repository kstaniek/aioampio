"""Model for climate/thermostat entity."""

from dataclasses import dataclass, field
from typing import Any
import logging

from .base import validate_numeric_value
from .resource import ResourceTypes

logger = logging.getLogger(__name__)


@dataclass
class Climate:
    """Represent a climate/thermostat resource."""

    id: str
    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None

    current_temperature: float | None = None
    target_temperature: float | None = None
    heating: bool | None = None
    state: bool | None = None

    type: ResourceTypes = ResourceTypes.CLIMATE

    # Reasonable temperature ranges (Celsius)
    _min_temperature: float = -50.0
    _max_temperature: float = 100.0

    def update(self, topic: str, data: dict[str, Any]) -> bool:  # noqa: ARG002
        """Update climate state from incoming data.

        Args:
            topic: Message topic (unused but kept for protocol consistency)
            data: Payload data with temperature, heating, and state keys

        Returns:
            True if any state changed, False otherwise
        """
        changed = False

        # Update current temperature
        if "current_temperature" in data:
            try:
                new_temp = validate_numeric_value(
                    data["current_temperature"],
                    min_val=self._min_temperature,
                    max_val=self._max_temperature,
                )
                if self.current_temperature != new_temp:
                    self.current_temperature = new_temp
                    changed = True
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Climate %s: Invalid current_temperature '%s': %s",
                    self.id,
                    data["current_temperature"],
                    e,
                )

        # Update target temperature
        if "target_temperature" in data:
            try:
                new_temp = validate_numeric_value(
                    data["target_temperature"],
                    min_val=self._min_temperature,
                    max_val=self._max_temperature,
                )
                if self.target_temperature != new_temp:
                    self.target_temperature = new_temp
                    changed = True
            except (ValueError, TypeError) as e:
                logger.warning(
                    "Climate %s: Invalid target_temperature '%s': %s",
                    self.id,
                    data["target_temperature"],
                    e,
                )

        # Update heating state
        if "heating" in data:
            try:
                new_heating = bool(data["heating"])
                if self.heating != new_heating:
                    self.heating = new_heating
                    changed = True
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Climate %s: Invalid heating value '%s': %s",
                    self.id,
                    data["heating"],
                    e,
                )

        # Update overall state
        if "state" in data:
            try:
                new_state = bool(data["state"])
                if self.state != new_state:
                    self.state = new_state
                    changed = True
            except (TypeError, ValueError) as e:
                logger.warning(
                    "Climate %s: Invalid state value '%s': %s",
                    self.id,
                    data["state"],
                    e,
                )

        return changed
