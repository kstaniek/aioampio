"""Model for text entity."""

from dataclasses import dataclass, field
from typing import Any

from .resource import ResourceTypes


@dataclass
class Text:
    """Represents Alarm Control Panel resource."""

    id: str
    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    state: str | None = None
    area: str | None = None

    type: ResourceTypes = ResourceTypes.TEXT

    def update(self, topic: str, data: dict[str, Any]) -> None:  # noqa: ARG002
        """Update text state from incoming data."""
        self.state = data.get("response")
