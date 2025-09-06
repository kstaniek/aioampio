"""Model for Ampio lights."""

from dataclasses import dataclass, field
from typing import Any

from .resource import ResourceTypes


@dataclass
class Switch:
    """Represent a light resource."""

    id: str
    on: bool
    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None

    state: dict[str, Any] | None = None

    type: ResourceTypes = ResourceTypes.SWITCH

    def update(self, topic: str, data: dict[str, Any]) -> None:  # noqa: ARG002
        """Update switch state from incoming data."""
        self.state = data.get("state")
