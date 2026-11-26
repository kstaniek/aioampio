"""Control panel for the alarm system."""

from dataclasses import dataclass, field
from typing import Any
import logging

from .resource import ResourceTypes

logger = logging.getLogger(__name__)


@dataclass
class AlarmControlPanel:
    """Represents an alarm control panel resource with multiple state flags."""

    id: str
    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None

    # Alarm state flags
    arming: bool | None = None
    arming_10s: bool | None = None
    armed: bool | None = None
    breached: bool | None = None
    alarm: bool | None = None

    type: ResourceTypes = ResourceTypes.ALARM_CONTROL_PANEL

    # Valid alarm attributes
    _valid_attributes = {"armed", "arming", "arming_10s", "breached", "alarm"}

    def update(self, topic: str, data: dict[str, Any]) -> bool:
        """Update the alarm control panel state.

        Args:
            topic: Message topic in format "prefix.attribute"
            data: Payload data containing 'state' key

        Returns:
            True if any state changed, False otherwise
        """
        # Extract attribute from topic
        parts = topic.split(".")
        if len(parts) < 2:
            logger.debug(
                "AlarmControlPanel %s: Invalid topic format '%s'", self.id, topic
            )
            return False

        attribute = parts[1]
        if attribute not in self._valid_attributes:
            logger.debug(
                "AlarmControlPanel %s: Unknown attribute '%s'", self.id, attribute
            )
            return False

        if "state" not in data:
            logger.debug("AlarmControlPanel %s: No 'state' in data", self.id)
            return False

        # Convert to bool
        try:
            new_state = bool(data["state"])
        except (TypeError, ValueError) as e:
            logger.warning(
                "AlarmControlPanel %s: Invalid state value '%s': %s",
                self.id,
                data["state"],
                e,
            )
            return False

        # Update the appropriate attribute
        old_value = getattr(self, attribute)
        if old_value == new_state:
            return False

        setattr(self, attribute, new_state)
        return True

    def get_state(self) -> dict[str, bool | None]:
        """Get complete alarm state as dictionary.

        Returns:
            Dictionary with all alarm state flags
        """
        return {
            "armed": self.armed,
            "arming": self.arming,
            "arming_10s": self.arming_10s,
            "breached": self.breached,
            "alarm": self.alarm,
        }
