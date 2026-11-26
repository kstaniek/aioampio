"""Lights Controller."""

import asyncio
from time import monotonic
from typing import TYPE_CHECKING

from aioampio.models.config import DeviceType
from aioampio.models.light import Light
from aioampio.models.resource import ResourceTypes

from .base import AmpioResourceController

if TYPE_CHECKING:
    from aioampio.bridge import AmpioBridge

# Rapid RGBW bursts can lose channels on physical modules/gateways.
RGBW_CHANNEL_INTERVAL_S = 0.01


class LightsController(AmpioResourceController[Light]):
    """Controller holding and managing Ampio resource type light."""

    item_type = ResourceTypes.LIGHT
    item_cls = Light

    def __init__(self, bridge: "AmpioBridge") -> None:
        """Keep RGBW channel groups and their pacing local to each module."""
        super().__init__(bridge)
        self._rgbw_locks: dict[str, asyncio.Lock] = {}
        self._rgbw_next_send: dict[str, float] = {}

    async def _set_rgbw(
        self, id: str, device_id: str, levels: tuple[int, int, int, int]
    ) -> None:
        """Serialize four-channel writes and leave time for physical delivery."""
        async with self._rgbw_locks.setdefault(device_id, asyncio.Lock()):
            for channel, level in enumerate(levels):
                delay = self._rgbw_next_send.get(device_id, 0) - monotonic()
                if delay > 0:
                    await asyncio.sleep(delay)
                await self._send_command(id, bytes((0x15, level & 0xFF, channel)))
                self._rgbw_next_send[device_id] = monotonic() + RGBW_CHANNEL_INTERVAL_S

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
                levels = (
                    color
                    if entity.supports_color and color is not None
                    else (0xFF if on else 0x00,) * 4
                )
                await self._set_rgbw(id, device.id, levels)
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
