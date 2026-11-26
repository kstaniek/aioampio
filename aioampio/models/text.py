"""Model for text entity."""

from dataclasses import dataclass, field
from typing import Any
import logging

from .resource import ResourceTypes

logger = logging.getLogger(__name__)


@dataclass
class Text:
    """Represents a text display/status resource."""

    id: str
    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    state: str | None = None
    area: str | None = None

    type: ResourceTypes = ResourceTypes.TEXT

    def update(self, topic: str, data: dict[str, Any]) -> bool:  # noqa: ARG002
        """Update text state from incoming data.

        Args:
            topic: Message topic (unused but kept for protocol consistency)
            data: Payload data containing 'response' key

        Returns:
            True if state changed, False otherwise
        """
        if "response" not in data:
            logger.debug("Text %s: No 'response' in data", self.id)
            return False

        # Convert to string
        try:
            new_state = str(data["response"]) if data["response"] is not None else None
        except (TypeError, ValueError) as e:
            logger.warning(
                "Text %s: Invalid response value '%s': %s",
                self.id,
                data["response"],
                e,
            )
            return False

        if self.state == new_state:
            return False

        self.state = new_state
        return True
