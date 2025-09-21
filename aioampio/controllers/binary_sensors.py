"""Binary Sensor Controller."""

from aioampio.controllers.base import AmpioResourceController
from aioampio.models.binary_sensor import BinarySensor
from aioampio.models.resource import ResourceTypes


class BinarySensorsController(AmpioResourceController[BinarySensor]):
    """Controller for managing binary sensor resources."""

    item_type = ResourceTypes.BINARY_SENSOR
    item_cls = BinarySensor
