"""Area controller."""

from __future__ import annotations

from aioampio.controllers.base import AmpioResourceController

from aioampio.models.resource import ResourceTypes
from aioampio.models.area import Area


class AreasController(AmpioResourceController[type[Area]]):
    """Controller for managing areas."""

    item_type = ResourceTypes.AREA
    item_cls = Area
