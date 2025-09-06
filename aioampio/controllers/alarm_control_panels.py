"""Alarm Control Panels Controller."""

from aioampio.controllers.base import AmpioResourceController
from aioampio.models.alarm_control_panel import AlarmControlPanel
from aioampio.models.resource import ResourceTypes
from .utils import get_trailing_number
from aioampio.codec.helper import generate_multican_payload


class AlarmControlPanelsController(AmpioResourceController[type[AlarmControlPanel]]):
    """Controller for managing alarm control panels."""

    item_type = ResourceTypes.ALARM_CONTROL_PANEL
    item_cls = AlarmControlPanel

    async def arm_in_mode0(self, id: str, code: str) -> None:  # noqa: ARG002
        device = self.get_device(id)
        if device is None:
            return
        zone_index = get_trailing_number(id)
        if zone_index is None:
            return

        if zone_index < 1:
            return

        zone_mask = (0x1 << (zone_index - 1)) & 0xFFFFFFFF
        zone_mask_bytes = zone_mask.to_bytes(4, "little")
        # 0x1E - SATEL, 0x00 - API_SATEL_SUB_CMD (0x00 - CMD PIN from PAR), 0x80 - SATEL CMD
        payload = bytes((0x1E, 0x00, 0x80)) + zone_mask_bytes
        for p in generate_multican_payload(device.can_id, payload):
            await self._bridge.transport.send(
                0x0F000000, data=p, extended=True, rtr=False
            )

    async def disarm(self, id: str, code: str) -> None:  # noqa: ARG002
        device = self.get_device(id)
        if device is None:
            return
        zone_index = get_trailing_number(id)
        if zone_index is None:
            return

        if zone_index < 1:
            return

        zone_mask = (0x1 << (zone_index - 1)) & 0xFFFFFFFF
        zone_mask_bytes = zone_mask.to_bytes(4, "little")
        # 0x1E - SATEL, 0x00 - API_SATEL_SUB_CMD (0x00 - CMD PIN from PAR), 0x80 - SATEL CMD
        payload = bytes((0x1E, 0x00, 0x84)) + zone_mask_bytes
        for p in generate_multican_payload(device.can_id, payload):
            await self._bridge.transport.send(
                0x0F000000, data=p, extended=True, rtr=False
            )
