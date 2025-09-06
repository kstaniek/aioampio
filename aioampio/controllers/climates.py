"""Climates Controller."""

from aioampio.models.climate import Climate
from aioampio.models.resource import ResourceTypes

from .base import AmpioResourceController
from .utils import get_entity_index


class ClimatesController(AmpioResourceController[type[Climate]]):
    """Controller holding and managing Ampio resource type climate."""

    item_type = ResourceTypes.CLIMATE
    item_cls = Climate

    async def set_state(
        self,
        id: str,
    ) -> None:
        """Set supported features to climate resource."""
        device = self.get_device(id)

        entity_index = get_entity_index(id)
        if entity_index is None:
            self._logger.error("Failed to extract climate number from id: %s", id)
            return

        entity = self.get(id)
        if entity is None or device is None:
            self._logger.error("Failed to find entity or device for id: %s", id)
            return
