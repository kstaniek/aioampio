"""Sensor Controller."""

from aioampio.controllers.base import AmpioResourceController
from aioampio.models.sensor import Sensor
from aioampio.models.resource import ResourceTypes


class SensorsController(AmpioResourceController[Sensor]):
    """Controller for managing sensor resources."""

    item_type = ResourceTypes.SENSOR
    item_cls = Sensor
