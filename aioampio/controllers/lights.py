"""Lights Controller."""

import asyncio
from time import monotonic
from typing import TYPE_CHECKING

from aioampio.models.config import DeviceType
from aioampio.models.base import validate_byte_value
from aioampio.models.light import Light
from aioampio.models.resource import ResourceTypes

from .base import AmpioResourceController
from .events import EventType
from .utils import get_entity_index

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
        self._member_groups: dict[str, set[str]] = {}
        self._rgbw_locks: dict[str, asyncio.Lock] = {}
        self._rgbw_next_send: dict[str, float] = {}

    def _notify_subscribers(
        self, evt_type: EventType, item_id: str, cur_item: Light | dict | None
    ) -> None:
        """Keep group dependencies separate from the raw feedback topic router."""
        if isinstance(cur_item, Light) and cur_item.members:
            if evt_type == EventType.RESOURCE_ADDED:
                for groups in self._member_groups.values():
                    groups.discard(item_id)
                for member_id in cur_item.members:
                    self._member_groups.setdefault(member_id, set()).add(item_id)
                cur_item.update_group(
                    [self._items.get(member) for member in cur_item.members]
                )
            elif evt_type == EventType.RESOURCE_DELETED:
                for member_id in cur_item.members:
                    containing_groups = self._member_groups.get(member_id)
                    if containing_groups is not None:
                        containing_groups.discard(item_id)
                        if not containing_groups:
                            self._member_groups.pop(member_id)
        super()._notify_subscribers(evt_type, item_id, cur_item)
        for group_id in tuple(self._member_groups.get(item_id, ())):
            group = self._items.get(group_id)
            if group is not None and group.update_group(
                [self._items.get(member) for member in group.members]
            ):
                super()._notify_subscribers(EventType.RESOURCE_UPDATED, group_id, group)

    def close(self) -> None:
        """Release raw subscriptions and group dependency bookkeeping."""
        super().close()
        self._member_groups.clear()

    async def _set_group_state(
        self,
        entity: Light,
        on: bool | None,
        brightness: int | None,
        color: tuple[int, int, int, int] | None,
    ) -> None:
        """Send exactly one validated mask, never a fan-out to member commands."""
        device = self.get_device(entity.id)
        if device is None or device.model != DeviceType.MLED or color is not None:
            raise ValueError("Masked light group requires an MLED module and no color")
        mask = 0
        for member_id in entity.members:
            member = self._items.get(member_id)
            index = get_entity_index(member_id)
            if member is None or member.owner != entity.owner or member.members:
                raise ValueError(f"Invalid masked light member: {member_id}")
            if member.supports_color or not member.supports_dimming:
                raise ValueError(f"Invalid masked light member: {member_id}")
            if index is None or not 0 <= index < 16 or mask & (1 << index):
                raise ValueError(f"Invalid masked light member: {member_id}")
            mask |= 1 << index
        if on is False:
            value = 0
        elif brightness is not None:
            value = validate_byte_value(brightness)
        else:
            value = 255 if on else 0
        await self._send_command(
            entity.id, bytes((0x14, value)) + mask.to_bytes(2, "little")
        )

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
        entity = self._items.get(id)
        if entity is None:
            self._logger.error("Entity %s not found", id)
            return

        if entity.members:
            await self._set_group_state(entity, on, brightness, color)
            return

        idx = self._get_entity_index_or_log(id)
        if idx is None:
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
