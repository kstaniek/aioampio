"""Model for cover entity."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
import logging

from aioampio.controllers.utils import get_entity_index
from aioampio.models.feature import CoverPositionFeature, TiltPositionFeature

from .base import validate_percentage
from .resource import ResourceTypes

logger = logging.getLogger(__name__)


class CoverState(StrEnum):
    """Enum for cover states."""

    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass
class Cover:
    """Represents a cover resource with position and tilt control."""

    id: str

    cover: CoverPositionFeature = field(default_factory=CoverPositionFeature)
    tilt: TiltPositionFeature = field(default_factory=TiltPositionFeature)
    state: CoverState = CoverState.UNKNOWN

    opening: bool = False
    closing: bool = False

    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.COVER

    # Entity index ranges
    _cover_position_indices = range(0, 4)  # 0-3: Cover position
    _tilt_position_indices = range(6, 10)  # 6-9: Tilt position

    def update(self, topic: str, data: dict[str, Any]) -> bool:
        """Update cover state from incoming data.

        Args:
            topic: Message topic
            data: Payload data

        Returns:
            True if state changed, False otherwise
        """
        entity_idx = get_entity_index(topic)
        if entity_idx is None:
            logger.debug("Cover %s: Could not extract entity index from topic", self.id)
            return False

        position_update = "value" in data and (
            entity_idx in self._cover_position_indices
            or entity_idx in self._tilt_position_indices
        )
        motion_update = "binout" in topic and "state" in data
        if not position_update and not motion_update:
            return False
        changed = False

        try:
            if position_update:
                position = validate_percentage(data["value"])
                changed |= self._update_position(entity_idx, position)

            # Update motion state
            if "binout" in topic and "state" in data:
                changed |= self._update_motion(entity_idx, data["state"])

            # Recompute overall state
            new_state = self._compute_state()
            if new_state != self.state:
                self.state = new_state
                changed = True

        except (ValueError, TypeError) as e:
            logger.warning(
                "Cover %s: Failed to update from topic '%s': %s", self.id, topic, e
            )
            return False

        return changed

    def _update_position(self, entity_idx: int, position: int) -> bool:
        """Update position based on entity index."""
        if entity_idx in self._cover_position_indices:
            if self.cover.position != position:
                self.cover.position = position
                return True
        elif entity_idx in self._tilt_position_indices:
            if self.tilt.position != position:
                self.tilt.position = position
                return True

        return False

    def _update_motion(self, entity_idx: int, state: Any) -> bool:
        """Update opening/closing state based on entity index."""
        motion_state = bool(state)
        changed = False

        # Odd indices = opening, even indices = closing
        if entity_idx % 2 == 1:
            if self.opening != motion_state:
                self.opening = motion_state
                if motion_state:
                    self.closing = False
                changed = True
        else:
            if self.closing != motion_state:
                self.closing = motion_state
                if motion_state:
                    self.opening = False
                changed = True

        return changed

    def _compute_state(self) -> CoverState:
        """Compute the overall cover state based on motion and position."""
        if self.opening and self.closing:
            raise RuntimeError(
                f"Cover {self.id}: Invalid state - cannot be opening and closing simultaneously"
            )

        if self.opening:
            return CoverState.OPENING
        if self.closing:
            return CoverState.CLOSING

        if self.cover.position == 0 and self.tilt.position == 0:
            return CoverState.CLOSED

        return CoverState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if cover is fully closed."""
        return self.state == CoverState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if cover is fully open."""
        return self.state == CoverState.OPEN

    @property
    def is_moving(self) -> bool:
        """Check if cover is currently moving."""
        return self.opening or self.closing
