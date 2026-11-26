"""Model for Ampio lights."""

from dataclasses import dataclass, field
from typing import Any
import logging

from .base import validate_byte_value
from .resource import ResourceTypes

logger = logging.getLogger(__name__)


@dataclass
class Light:
    """Represent a light resource with dimming and color support."""

    id: str
    on: bool
    name: str = ""
    dimming: bool = False
    color: bool = False
    states: list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    type: ResourceTypes = ResourceTypes.LIGHT

    state: dict[str, Any] = field(default_factory=dict)
    _rgb_channels: dict[str, bool] = field(default_factory=dict)
    _rgb_channel_count: int = 4  # R, G, B, W

    @property
    def supports_dimming(self) -> bool:
        """Check if the light supports dimming."""
        return self.dimming

    @property
    def supports_color(self) -> bool:
        """Check if the light supports color."""
        return self.color

    def update(self, topic: str, data: dict[str, Any]) -> bool:
        """Update light state from incoming data.

        Args:
            topic: Message topic
            data: Payload data

        Returns:
            True if state changed, False otherwise
        """
        changed = False

        try:
            if "rgb" in topic:
                changed = self._update_rgb_color(data)
            elif "aout" in topic:
                changed = self._update_brightness(data)
            elif "binout" in topic:
                changed = self._update_on_state(topic, data)
            else:
                logger.debug("Light %s: Unknown topic pattern '%s'", self.id, topic)

        except (ValueError, TypeError, KeyError) as e:
            logger.warning(
                "Light %s: Failed to update from topic '%s': %s", self.id, topic, e
            )
            return False

        return changed

    def _update_rgb_color(self, data: dict[str, Any]) -> bool:
        """Update RGB color values."""
        changed = False
        for color in ["red", "green", "blue", "white"]:
            if color in data:
                try:
                    new_value = validate_byte_value(data[color])
                    old_value = self.state.get(color)
                    if old_value != new_value:
                        self.state[color] = new_value
                        changed = True
                except ValueError as e:
                    logger.warning(
                        "Light %s: Invalid %s value '%s': %s",
                        self.id,
                        color,
                        data[color],
                        e,
                    )

        return changed

    def _update_brightness(self, data: dict[str, Any]) -> bool:
        """Update brightness from analog output."""
        if "value" not in data:
            return False

        try:
            new_brightness = validate_byte_value(data["value"])
            old_brightness = self.state.get("brightness")
            if old_brightness != new_brightness:
                self.state["brightness"] = new_brightness
                return True
        except ValueError as e:
            logger.warning(
                "Light %s: Invalid brightness value '%s': %s",
                self.id,
                data["value"],
                e,
            )

        return False

    def _update_on_state(self, topic: str, data: dict[str, Any]) -> bool:
        """Update on/off state from binary output."""
        if "state" not in data:
            return False

        new_state = bool(data["state"])

        if self.supports_color:
            # Track individual RGB channel states
            self._rgb_channels[topic] = new_state

            # Only update overall state when all channels are known
            if len(self._rgb_channels) == self._rgb_channel_count:
                combined_state = any(self._rgb_channels.values())
                old_state = self.state.get("state")
                if old_state != combined_state:
                    self.state["state"] = combined_state
                    return True
            return False

        # Simple on/off light
        old_state = self.state.get("state")
        if old_state != new_state:
            self.state["state"] = new_state
            return True
        return False
