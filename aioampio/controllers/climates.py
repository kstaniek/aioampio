"""Validated M-RT heating-zone commands."""

import asyncio
from decimal import Decimal, ROUND_HALF_UP
import math
import re
import struct

from aioampio.models.climate import Climate
from aioampio.models.config import DeviceType
from aioampio.models.resource import ResourceTypes

from .base import AmpioResourceController


class ClimatesController(AmpioResourceController[Climate]):
    """Control setpoints and modes 0-3, retaining receive-only state updates."""

    item_type = ResourceTypes.CLIMATE
    item_cls = Climate

    def __init__(self, *args, **kwargs) -> None:
        """Serialize climate command transactions, including multiframe modes."""
        super().__init__(*args, **kwargs)
        self._command_lock = asyncio.Lock()

    def _zone_index(self, id: str) -> int | None:
        entity = self.get(id)
        device = self.get_device(id)
        if entity is None or device is None or device.model != DeviceType.MRT16S:
            return None
        heating = [state for state in entity.states if state.startswith("heating.")]
        if len(heating) != 1:
            return None
        match = re.fullmatch(r"heating\.([1-9]|1[0-6])", heating[0])
        if match is None:
            return None
        zone = int(match[1])
        if any(
            state.startswith("zone.") and state != f"zone.{zone}"
            for state in entity.states
        ):
            return None
        return zone - 1

    def supports_control(self, id: str) -> bool:
        """Return whether the module and configured zone have a validated writer."""
        return self._zone_index(id) is not None

    async def set_temperature(self, id: str, temperature: float) -> None:
        """Write a Celsius setpoint; the module selects temporary mode 2."""
        await self.set_state(id, temperature=temperature)

    async def set_mode(self, id: str, mode: int) -> None:
        """Write calendar/manual/temporary/holiday mode; off/block is unsupported."""
        await self.set_state(id, mode=mode)

    async def set_state(
        self, id: str, *, temperature: float | None = None, mode: int | None = None
    ) -> None:
        """Validate the entire request before sending, without optimistic updates."""
        index = self._zone_index(id)
        entity = self.get(id)
        if index is None or entity is None:
            raise ValueError(
                "Climate control requires an M-RT module and one matching heating zone"
            )
        if temperature is None and mode is None:
            raise ValueError("Specify a temperature or mode")
        encoded_temperature = None
        if temperature is not None:
            if isinstance(temperature, bool) or not isinstance(
                temperature, (int, float)
            ):
                raise ValueError("Temperature must be a finite number")
            if (
                not math.isfinite(temperature)
                or not entity.min_temperature <= temperature <= entity.max_temperature
            ):
                raise ValueError("Temperature is outside the configured Celsius limits")
            encoded_temperature = int(
                (Decimal(str(temperature)) * 10).quantize(
                    Decimal("1"), rounding=ROUND_HALF_UP
                )
            )
        if mode is not None and (
            isinstance(mode, bool) or not isinstance(mode, int) or mode not in range(4)
        ):
            raise ValueError("Climate mode must be an integer from 0 through 3")
        async with self._command_lock:
            if encoded_temperature is not None:
                await self._send_command(
                    id, bytes((0x13, index)) + struct.pack("<H", encoded_temperature)
                )
            if mode is not None:
                await self._send_multiframe_command(
                    id, bytes((0x08, index, 0x02, mode))
                )
