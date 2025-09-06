"""Valves Controller."""

from aioampio.models.valve import Valve
from aioampio.models.resource import ResourceTypes
from .base import AmpioResourceController


class ValvesController(AmpioResourceController[type[Valve]]):
    """Controller holding and managing Ampio resource type cover."""

    item_type = ResourceTypes.VALVE
    item_cls = Valve

    _CMD_VALVE_OPEN = 0x02
    _CMD_VALVE_CLOSE = 0x01
    _CMD_VALVE_STOP = 0x00

    async def open_valve(self, id: str) -> None:
        """Open the valve."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return
        command = bytes((0x31, 0xF9, self._CMD_VALVE_OPEN, idx & 0xFF))
        await self._send_multiframe_command(id, command)

    async def close_valve(self, id: str) -> None:
        """Close the valve."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return
        command = bytes((0x31, 0xF9, self._CMD_VALVE_CLOSE, idx & 0xFF))
        await self._send_multiframe_command(id, command)

    async def stop_valve(self, id: str) -> None:
        """Stop the valve."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return

        command = bytes((0x31, 0xF9, self._CMD_VALVE_STOP, idx & 0xFF))
        await self._send_multiframe_command(id, command)

    async def set_position(self, id: str, position: int | None = None) -> None:
        """Set the valve position."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return

        position_value = 0x65  # ignore
        if position is not None:
            position_value = max(0, min(100, position))

        command = bytes(
            (0x31, 0x03, idx & 0xFF, 0x00, 0x00, position_value & 0xFF, 0x65)
        )
        await self._send_multiframe_command(id, command)
