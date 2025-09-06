"""Controller for managing Ampio devices."""

from .base import AmpioResourceController
from aioampio.models.resource import ResourceTypes
from aioampio.models.device import Device


class DevicesController(AmpioResourceController[type[Device]]):
    """Controller for managing Ampio devices."""

    item_type = ResourceTypes.DEVICE
    item_cls = Device
