"""Alarm Control Panels Controller."""

from aioampio.controllers.base import AmpioResourceController
from aioampio.models.alarm_control_panel import AlarmControlPanel
from aioampio.models.resource import ResourceTypes
from .utils import get_entity_index


SATEL_CTRL_CAN_ID = 0x0F002000


def pin_to_satel(pin: str) -> bytes:
    """
    Convert a numeric string PIN (max 16 digits) to 8 bytes.
    Each digit is encoded in 4 bits (high nibble first digit, low nibble second, etc).
    The result is padded with 0xFF to 8 bytes if needed.
    This is a more compact implementation.
    """
    if not (pin.isdigit() and len(pin) <= 16):
        raise ValueError("PIN must be a numeric string up to 16 digits.")
    # Convert pin digits to nibbles and pad with 0xF
    nibbles = [int(d) for d in pin] + [0xF] * (16 - len(pin))
    return bytes(((nibbles[i] << 4) | nibbles[i + 1]) for i in range(0, 16, 2))


class AlarmControlPanelsController(AmpioResourceController[type[AlarmControlPanel]]):
    """Controller for managing alarm control panels."""

    item_type = ResourceTypes.ALARM_CONTROL_PANEL
    item_cls = AlarmControlPanel

    async def _send_alarm_command(self, id: str, code: str, command: int) -> None:
        """Helper to send alarm command with given command byte."""
        device = self.get_device(id)
        if device is None:
            return
        zone_index = get_entity_index(id)
        if zone_index is None:
            return

        try:
            pin = pin_to_satel(code)
        except ValueError:
            self._logger.error("Invalid PIN code for alarm command")
            return

        # Create a 4-byte little-endian zone mask with the bit at zone_index set
        zone_mask = (1 << zone_index).to_bytes(4, "little")

        # Build the payload:
        # 0x14, 0x0D: Command header
        # command: Command byte (e.g., arm/disarm)
        # pin: Encoded PIN as 8 bytes
        # zone_mask: 4-byte little-endian mask for the target zone
        payload = bytes((0x14, 0x0D, command)) + pin + zone_mask
        await self._send_multiframe_command(id, payload)

    async def arm_in_mode0(self, id: str, code: str) -> None:
        """Arm the alarm in mode 0 (stay)."""
        await self._send_alarm_command(id, code, 0x80)

    async def disarm(self, id: str, code: str) -> None:
        """Disarm the alarm."""
        await self._send_alarm_command(id, code, 0x84)
