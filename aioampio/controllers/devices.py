"""Controller for managing Ampio devices."""

from aioampio.models.device import Device
from aioampio.models.resource import ResourceTypes

from .base import AmpioResourceController


class DevicesController(AmpioResourceController[type[Device]]):
    """Controller for managing Ampio devices."""

    item_type = ResourceTypes.DEVICE
    item_cls = Device
