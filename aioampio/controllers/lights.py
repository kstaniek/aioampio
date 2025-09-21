"""Lights Controller."""

from aioampio.models.config import DeviceType
from aioampio.models.light import Light
from aioampio.models.resource import ResourceTypes

from .base import AmpioResourceController


class LightsController(AmpioResourceController[Light]):
    """Controller holding and managing Ampio resource type light."""

    item_type = ResourceTypes.LIGHT
    item_cls = Light

    async def set_state(  # pylint: disable=too-many-branches
        self,
        id: str,
        on: bool | None = None,
        brightness: int | None = None,
        color: tuple[int, int, int, int] | None = None,
    ) -> None:
        """Set supported features to light resource."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return

        entity = self._items.get(id)
        if entity is None:
            self._logger.error("Entity %s not found", id)
            return

        device = self._bridge.devices.get(entity.owner) if entity.owner else None
        if device is None:
            self._logger.error("Device for entity %s not found", id)
            return

        match device.model:
            case DeviceType.MRGBW:
                if brightness is not None:
                    self._logger.warning(
                        "Brightness control not supported for color lights"
                    )
                if entity.supports_color and color is not None:
                    for i in range(4):
                        payload = bytes((0x15, color[i] & 0xFF, i & 0xFF))
                        await self._send_command(id, payload)
                else:
                    for i in range(4):
                        payload = bytes((0x15, 0xFF if on else 0x00, i & 0xFF))
                        await self._send_command(id, payload)
                return

            case (
                DeviceType.MLED
                | DeviceType.MINOC4P
                | DeviceType.MDIM
                | DeviceType.MREL8S
            ):
                if entity.supports_dimming and brightness is not None:
                    command = bytes((0x15, brightness & 0xFF, idx & 0xFF, 0x00))
                    await self._send_command(id, command)
                else:
                    command = bytes((0x15, 0xFF if on else 0x00, idx & 0xFF, 0x00))
                    await self._send_command(id, command)
                return

            case _:
                # Other
                if entity.supports_dimming and brightness is not None:
                    command = bytes((0x36, 0xF9, brightness & 0xFF, idx & 0xFF))
                    await self._send_multiframe_command(id, command)
                else:
                    command = bytes((0x30, 0xF9, 0x01 if on else 0x00, idx))
                    await self._send_multiframe_command(id, command)
