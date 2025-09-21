"""Alarm Control Panels Controller."""

from aioampio.controllers.base import AmpioResourceController
from aioampio.models.text import Text
from aioampio.models.resource import ResourceTypes


class TextsController(AmpioResourceController[Text]):
    """Controller for managing text resources."""

    item_type = ResourceTypes.TEXT
    item_cls = Text
