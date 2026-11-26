"""Model for switch entity."""

from dataclasses import dataclass, field
from typing import Any
import logging

from .resource import ResourceTypes

logger = logging.getLogger(__name__)


@dataclass
class Switch:
    """Represent a switch resource (on/off control)."""

    id: str
    on: bool
    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    device_class: str | None = None

    state: bool | None = None

    type: ResourceTypes = ResourceTypes.SWITCH

    def update(self, topic: str, data: dict[str, Any]) -> bool:  # noqa: ARG002
        """Update switch state from incoming data.

        Args:
            topic: Message topic (unused but kept for protocol consistency)
            data: Payload data containing 'state' key

        Returns:
            True if state changed, False otherwise
        """
        if "state" not in data:
            logger.debug("Switch %s: No 'state' in data", self.id)
            return False

        try:
            new_state = bool(data["state"])
        except (TypeError, ValueError) as e:
            logger.warning(
                "Switch %s: Invalid state value '%s': %s", self.id, data["state"], e
            )
            return False

        if self.state == new_state:
            return False

        self.state = new_state
        return True
