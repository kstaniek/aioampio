"""Model for Ampio lights."""

from dataclasses import dataclass, field
from typing import Any

from .resource import ResourceTypes


@dataclass
class Light:
    """Represent a light resource."""

    id: str
    on: bool
    name: str = ""
    dimming: bool = False
    color: bool = False
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    type: ResourceTypes = ResourceTypes.LIGHT

    state: dict[str, Any] = field(default_factory=dict)
    _rgb_state: dict[str, bool] = field(default_factory=dict)

    @property
    def supports_dimming(self) -> bool:
        """Check if the light supports dimming."""
        return self.dimming

    @property
    def supports_color(self) -> bool:
        """Check if the light supports color."""
        return self.color

    def update(self, topic: str, data: dict[str, Any]) -> None:
        """Update light state from incoming data."""
        if "rgb" in topic and self.state is not None:
            self.state.update(data)
        if "aout" in topic and "value" in data:
            self.state.update({"brightness": data["value"]})
        if "binout" in topic and "state" in data:
            if self.supports_color:
                state = False
                self._rgb_state[topic] = data["state"]
                if len(self._rgb_state) == 4:
                    for s in self._rgb_state.values():
                        state = state or s
                    self.state.update({"state": state})
            else:
                self.state.update({"state": data["state"]})
