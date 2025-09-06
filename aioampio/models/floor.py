"""Model for floor entity."""

from dataclasses import dataclass, field

from .resource import ResourceTypes
from .area import Area


@dataclass
class Floor:
    """Represents Floor resource."""

    id: str
    name: str = ""
    level: int = 0

    areas: list[Area] = field(default_factory=list)

    type: ResourceTypes = ResourceTypes.FLOOR
