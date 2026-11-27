"""Model for climate/thermostat entity."""

from dataclasses import dataclass, field
from typing import Any, ClassVar
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
    mode: int | None = None
    min_temperature: float = 7.0
    max_temperature: float = 35.0

    type: ResourceTypes = ResourceTypes.CLIMATE

    # Reasonable temperature ranges (Celsius)
    _min_temperature: ClassVar[float] = -50.0
    _max_temperature: ClassVar[float] = 100.0

    def update(self, topic: str, data: dict[str, Any]) -> bool:  # noqa: ARG002
        """Update climate state from incoming data.

        Args:
            topic: Message topic (unused but kept for protocol consistency)
            data: Payload data with temperature, heating, and state keys

        Returns:
            True if any state changed, False otherwise
        """
        changed = self._update_mode(data.get("operating_mode"))

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

    def _update_mode(self, mode: Any) -> bool:
        """Preserve unknown numeric modes without accepting booleans."""
        if (
            isinstance(mode, bool)
            or not isinstance(mode, int)
            or not 0 <= mode <= 7
            or self.mode == mode
        ):
            return False
        self.mode = mode
        return True
