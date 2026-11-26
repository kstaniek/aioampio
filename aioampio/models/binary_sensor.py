"""Model for binary sensor entity."""

from dataclasses import dataclass, field
from typing import Any
import logging

from .resource import ResourceTypes

logger = logging.getLogger(__name__)


@dataclass
class BinarySensor:
    """Represents a binary sensor resource.

    Binary sensors have two states: on/off, true/false, detected/not detected, etc.
    The exact interpretation depends on the device_class.
    """

    id: str
    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    state: bool | None = None
    area: str | None = None
    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.BINARY_SENSOR

    def update(self, topic: str, data: dict[str, Any]) -> bool:  # noqa: ARG002
        """Update binary sensor state from incoming data.

        Args:
            topic: Message topic (unused but kept for protocol consistency)
            data: Payload data containing 'state' key

        Returns:
            True if state changed, False otherwise
        """
        if "state" not in data:
            logger.debug("BinarySensor %s: No 'state' in data", self.id)
            return False

        # Convert to bool for type safety
        try:
            new_state = bool(data["state"])
        except (TypeError, ValueError) as e:
            logger.warning(
                "BinarySensor %s: Invalid state value '%s': %s",
                self.id,
                data["state"],
                e,
            )
            return False

        if self.state == new_state:
            return False

        self.state = new_state
        return True
