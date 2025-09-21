"""Lights Controller."""

from aioampio.models.switch import Switch
from aioampio.models.resource import ResourceTypes
from .base import AmpioResourceController


class SwitchesController(AmpioResourceController[Switch]):
    """Controller holding and managing Ampio resource type switch."""

    item_type = ResourceTypes.SWITCH
    item_cls = Switch

    async def set_state(
        self,
        id: str,
        on: bool | None = None,
    ) -> None:
        """Set supported features to switch resource."""
        idx = self._get_entity_index_or_log(id)
        if idx is None:
            return

        if "flag" in id:
            # 01 00 - sterowanie flagami czasowe
            #       01000000 - maska
            #               FFC800
            # 01 00 01000000FFC80000
            command = bytes((0x2F, 0xF9, 0x01 if on else 0x00, idx & 0xFF))
            await self._send_multiframe_command(id, command)
            # for p in generate_multican_payload(device.can_id, payload):
            #     await self._bridge.transport.send(
            #         0x0F000000, data=p, extended=True, rtr=False
            #     )

        else:
            command = bytes((0x15, 0xFF if on else 0x00, idx & 0xFF))
            await self._send_command(id, command)

            # payload = struct.pack(">I", device.can_id) + p
            # await self._bridge.transport.send(
            #     0x0F000000, data=payload, extended=True, rtr=False
            # )
