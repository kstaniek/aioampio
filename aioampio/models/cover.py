"""Model for cover entity."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from aioampio.controllers.utils import get_entity_index
from aioampio.models.feature import CoverPositionFeature, TiltPositionFeature

from .resource import ResourceTypes


class CoverState(StrEnum):
    """Enum for cover states."""

    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"


@dataclass
class Cover:
    """Represents a cover resource."""

    id: str

    cover: CoverPositionFeature = field(default_factory=CoverPositionFeature)
    tilt: TiltPositionFeature = field(default_factory=TiltPositionFeature)
    state: CoverState | None = None

    opening: bool = False
    closing: bool = False

    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.COVER

    def update(self, topic: str, data: dict[str, Any]) -> None:
        """Update cover state from incoming data."""
        entity_idx = get_entity_index(topic)
        if entity_idx is not None:
            position = data.get("value", 0)
            if entity_idx < 4:  # cover
                self.cover.position = position
            elif entity_idx > 5 and entity_idx < 10:  # pylint: disable=chained-comparison
                self.tilt.position = position

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
            self.state = CoverState.OPENING
        elif self.closing:
            self.state = CoverState.CLOSING
        elif self.tilt.position == 0 and self.cover.position == 0:
            self.state = CoverState.CLOSED
        else:
            self.state = CoverState.OPEN
