"""Covers Controller."""

from aioampio.models.cover import Cover
from aioampio.models.resource import ResourceTypes
from .base import AmpioResourceController


class CoversController(AmpioResourceController[type[Cover]]):
    """Controller holding and managing Ampio resource type cover."""

    item_type = ResourceTypes.COVER
    item_cls = Cover

    _CMD_COVER_OPEN = 0x02
    _CMD_COVER_CLOSE = 0x01
    _CMD_COVER_STOP = 0x00

    async def open_cover(self, id: str) -> None:
        """Open the cover."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return
        command = bytes((0x31, 0xF9, self._CMD_COVER_OPEN, idx & 0xFF))
        await self._send_multiframe_command(id, command)

    async def close_cover(self, id: str) -> None:
        """Close the cover."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return
        command = bytes((0x31, 0xF9, self._CMD_COVER_CLOSE, idx & 0xFF))
        await self._send_multiframe_command(id, command)

    async def stop_cover(self, id: str) -> None:
        """Stop the cover."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return
        command = bytes((0x31, 0xF9, self._CMD_COVER_STOP, idx & 0xFF))
        await self._send_multiframe_command(id, command)

    async def open_tilt(self, id: str) -> None:
        """Open the cover tilt."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return
        command = bytes((0x31, 0x03, idx & 0xFF, 0x00, 0x00, 0x65, 0x64))
        await self._send_multiframe_command(id, command)

    async def close_tilt(self, id: str) -> None:
        """Close the cover tilt."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return
        command = bytes((0x31, 0x03, idx & 0xFF, 0x00, 0x00, 0x65, 0x00))
        await self._send_multiframe_command(id, command)

    async def stop_tilt(self, id: str) -> None:
        """Stop the cover tilt."""
        await self.stop_cover(id)

    async def set_position(
        self, id: str, position: int | None = None, tilt_position: int | None = None
    ) -> None:
        """Set the cover position and/or tilt position."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return

        position_value = 0x65 if position is None else max(0, min(100, position))
        tilt_position_value = (
            0x65 if tilt_position is None else max(0, min(100, tilt_position))
        )
        command = bytes(
            (0x31, 0x03, idx, 0x00, 0x00, position_value, tilt_position_value)
        )
        await self._send_multiframe_command(id, command)
