"""Model for binary sensor entity."""

from dataclasses import dataclass, field
from typing import Any

from .resource import ResourceTypes


@dataclass
class BinarySensor:
    """Represents a binary sensor resource."""

    id: str
    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    state: str | None = None
    area: str | None = None

    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.BINARY_SENSOR

    def update(self, topic: str, data: dict[str, Any]) -> None:  # noqa: ARG002
        self.state = data.get("state")
