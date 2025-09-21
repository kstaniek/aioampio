"""Area controller."""

from __future__ import annotations

from aioampio.controllers.base import AmpioResourceController

from aioampio.models.resource import ResourceTypes
from aioampio.models.floor import Floor


class FloorsController(AmpioResourceController[Floor]):
    """Controller for managing floors."""

    item_type = ResourceTypes.FLOOR
    item_cls = Floor
