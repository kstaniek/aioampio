"""Model for Ampio lights."""

from dataclasses import dataclass, field
from typing import Any

from .resource import ResourceTypes


@dataclass
class Climate:
    """Represent a climate resource."""

    id: str
    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None

    current_temperature: float | None = None
    target_temperature: float | None = None
    heating: bool | None = None
    state: bool | None = None

    type: ResourceTypes = ResourceTypes.CLIMATE

    def update(self, topic: str, data: dict[str, Any]) -> None:  # noqa: ARG002
        """Update climate state from incoming data."""
        self.current_temperature = data.get(
            "current_temperature", self.current_temperature
        )
        self.target_temperature = data.get(
            "target_temperature", self.target_temperature
        )
        self.heating = data.get("heating", self.heating)
        self.state = data.get("state", self.state)
