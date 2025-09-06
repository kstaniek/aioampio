"""Model for area entity."""

from dataclasses import dataclass

from .resource import ResourceTypes


@dataclass
class Area:
    """Represents Area resource."""

    id: str
    name: str = ""
    icon: str | None = None
    floor_name: str | None = None

    type: ResourceTypes = ResourceTypes.AREA
