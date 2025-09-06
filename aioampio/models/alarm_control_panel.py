"""Control panel for the alarm system."""

from dataclasses import dataclass, field
from typing import Any

from .resource import ResourceTypes


@dataclass
class AlarmControlPanel:
    """Represents Alarm Control Panel resource."""

    id: str
    name: str = ""
    states: str | list[str] = field(default_factory=list)
    owner: str | None = None
    area: str | None = None
    arming: bool | None = None
    arming_10s: bool | None = None
    armed: bool | None = None
    breached: bool | None = None
    alarm: bool | None = None
    state: dict[str, Any] = field(default_factory=dict)

    type: ResourceTypes = ResourceTypes.ALARM_CONTROL_PANEL

    def update(self, topic: str, data: dict[str, Any]) -> None:
        """Update the alarm control panel state."""
        attribute = topic.split(".")[1]
        if attribute == "armed":
            self.armed = bool(data.get("state", False))
        elif attribute == "arming":
            self.arming = bool(data.get("state", False))
        elif attribute == "arming_10s":
            self.arming_10s = bool(data.get("state", False))
        elif attribute == "breached":
            self.breached = bool(data.get("state", False))
        elif attribute == "alarm":
            self.alarm = bool(data.get("state", False))

        self.state.update(
            {
                "armed": self.armed,
                "arming": self.arming,
                "arming_10s": self.arming_10s,
                "breached": self.breached,
                "alarm": self.alarm,
            }
        )
