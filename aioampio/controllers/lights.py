"""Lights Controller."""

from aioampio.models.config import DeviceType
from .base import AmpioResourceController
from aioampio.models.resource import ResourceTypes
from aioampio.models.light import Light


class LightsController(AmpioResourceController[type[Light]]):
    """Controller holding and managing Ampio resource type light."""

    item_type = ResourceTypes.LIGHT
    item_cls = Light

    async def set_state(
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

        if hasattr(entity, "supports_color") and entity.supports_color:
            if brightness is not None:
                self._logger.warning(
                    "Brightness control not supported for color lights"
                )
            if color is not None:
                payload = bytes(
                    (
                        0x02,
                        0x00,
                        color[0] & 0xFF,
                        color[1] & 0xFF,
                        color[2] & 0xFF,
                        color[3] & 0xFF,
                    )
                )  # 0x02 0x00 <red> <green> <blue> <white>
                await self._send_multiframe_command(id, payload)
                # for p in generate_multican_payload(device.can_id, payload):
                #     await self._bridge.transport.send(
                #         0x0F000000, data=p, extended=True, rtr=False
                #     )

            else:
                for i in range(4):
                    payload = bytes((0x15, 0xFF if on else 0x00, i & 0xFF))
                    await self._send_command(id, payload)
                    # await self._bridge.transport.send(
                    #     0x0F000000, data=payload, extended=True, rtr=False
                    # )
            return

        if device.model is DeviceType.MDIM:
            if entity.dimming and brightness is not None:
                if device.model is DeviceType.MDIM:  # use old command
                    command = bytes((0x07, idx, brightness & 0xFF, 0x00))
                    await self._send_command(id, command)
                    # payload = struct.pack(">I", device.can_id) + p
                    # await self._bridge.transport.send(
                    #     0x0F000000, data=payload, extended=True, rtr=False
                    # )
            else:
                command = bytes((0x15, 0xFF if on else 0x00, idx & 0xFF))
                await self._send_command(id, command)
                # payload = struct.pack(">I", device.can_id) + p
                # await self._bridge.transport.send(
                #     0x0F000000, data=payload, extended=True, rtr=False
                # )
        elif entity.dimming and brightness is not None:
            command = bytes((0x36, 0xF9, brightness & 0xFF, idx & 0xFF))
            await self._send_multiframe_command(id, command)

            # for _ in range(2):
            #     async with self._bridge.transport.client.atomic(0x0F000000) as a:
            #         for p in generate_multican_payload(device.can_id, payload):
            #             await a.send(p)
            # # for p in generate_multican_payload(device.can_id, payload):
            #     await self._bridge.transport.send(
            #     0x0F000000, data=p, extended=True, rtr=False
            #     )

        else:
            # payload = bytes((0x36, 0xf9, 0xff if on else 0x00, entity_index & 0xff))
            command = bytes((0x30, 0xF9, 0x01 if on else 0x00, idx))
            await self._send_multiframe_command(id, command)

            # for _ in range(2):
            #     async with self._bridge.transport.client.atomic(0x0F000000) as a:
            #         for p in generate_multican_payload(device.can_id, payload):
            #             await a.send(p)
            #         # for p in generate_multican_payload(device.can_id, payload):
            #     await self._bridge.transport.send(
            #         0x0F000000, data=p, extended=True, rtr=False
            #     )
