"""Model for cover entity."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aioampio.controllers.utils import get_entity_index
from aioampio.models.feature import ValvePositionFeature

from .resource import ResourceTypes


class ValveState(StrEnum):
    """Enum for valve states."""

    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class Valve:
    """Represents a valve resource."""

    id: str

    valve: ValvePositionFeature = field(default_factory=ValvePositionFeature)
    state: ValveState | None = None

    opening: bool = False
    closing: bool = False

    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.VALVE

    def update(self, topic: str, data: dict[str, Any]) -> None:
        entity_idx = get_entity_index(topic)
        if entity_idx is not None:
            if entity_idx < 4:  # valve
                self.valve.position = data.get("value", 0)

            if "binout" in topic:
                state = data.get("state", False)
                if entity_idx % 2 == 1:
                    self.opening = state
                    self.closing = False
                else:
                    self.closing = state
                    self.opening = False

        if self.opening and self.closing:
            raise RuntimeError("Cover cannot be opening and closing at the same time")
        if self.opening:
            self.state = ValveState.OPENING
        elif self.closing:
            self.state = ValveState.CLOSING
        elif self.valve.position == 0:
            self.state = ValveState.CLOSED
        else:
            self.state = ValveState.OPEN
