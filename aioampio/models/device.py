"""Device models for the Ampio devices."""

from dataclasses import dataclass

from .resource import ResourceTypes
from .config import DeviceType


@dataclass
class Device:
    """Represent an Ampio device."""

    id: str
    can_id: int
    model: DeviceType
    name: str
    manufacturer: str = "Ampio Systems"
    pcb: int = 0
    sw_version: int = 0
    area: str | None = None

    type: ResourceTypes = ResourceTypes.DEVICE
