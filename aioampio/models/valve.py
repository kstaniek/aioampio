"""Model for valve entity."""

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any
import logging

from aioampio.controllers.utils import get_entity_index
from aioampio.models.feature import ValvePositionFeature

from .base import validate_percentage
from .resource import ResourceTypes

logger = logging.getLogger(__name__)


class ValveState(StrEnum):
    """Enum for valve states."""

    OPENING = "opening"
    OPEN = "open"
    CLOSING = "closing"
    CLOSED = "closed"
    UNKNOWN = "unknown"


@dataclass
class Valve:
    """Represents a valve resource with position control."""

    id: str

    valve: ValvePositionFeature = field(default_factory=ValvePositionFeature)
    state: ValveState = ValveState.UNKNOWN

    opening: bool = False
    closing: bool = False

    name: str = ""
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    device_class: str | None = None

    type: ResourceTypes = ResourceTypes.VALVE

    # Entity index range for valve positions
    _valve_position_indices = range(0, 4)  # 0-3: Valve position

    def update(self, topic: str, data: dict[str, Any]) -> bool:
        """Update valve state from incoming data.

        Args:
            topic: Message topic
            data: Payload data

        Returns:
            True if state changed, False otherwise
        """
        entity_idx = get_entity_index(topic)
        if entity_idx is None:
            logger.debug("Valve %s: Could not extract entity index from topic", self.id)
            return False

        changed = False

        try:
            # Update position
            if "value" in data and entity_idx in self._valve_position_indices:
                try:
                    position = validate_percentage(data["value"])
                    if self.valve.position != position:
                        self.valve.position = position
                        changed = True
                except ValueError as e:
                    logger.warning(
                        "Valve %s: Invalid position value '%s': %s",
                        self.id,
                        data["value"],
                        e,
                    )

            # Update motion state
            if "binout" in topic and "state" in data:
                motion_state = bool(data["state"])

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

            # Recompute overall state
            new_state = self._compute_state()
            if new_state != self.state:
                self.state = new_state
                changed = True

        except (ValueError, TypeError) as e:
            logger.warning(
                "Valve %s: Failed to update from topic '%s': %s", self.id, topic, e
            )
            return False

        return changed

    def _compute_state(self) -> ValveState:
        """Compute the overall valve state based on motion and position.

        Returns:
            Computed valve state

        Raises:
            RuntimeError: If valve is both opening and closing (invalid state)
        """
        # Validate state consistency
        if self.opening and self.closing:
            raise RuntimeError(
                f"Valve {self.id}: Invalid state - cannot be opening and closing simultaneously"
            )

        # Motion takes precedence
        if self.opening:
            return ValveState.OPENING
        if self.closing:
            return ValveState.CLOSING

        # Determine state from position
        if self.valve.position == 0:
            return ValveState.CLOSED

        return ValveState.OPEN

    @property
    def is_closed(self) -> bool:
        """Check if valve is fully closed."""
        return self.state == ValveState.CLOSED

    @property
    def is_open(self) -> bool:
        """Check if valve is fully open."""
        return self.state == ValveState.OPEN

    @property
    def is_moving(self) -> bool:
        """Check if valve is currently moving."""
        return self.opening or self.closing
