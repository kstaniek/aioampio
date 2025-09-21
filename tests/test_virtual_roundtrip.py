# tests/test_virtual_roundtrip.py
import asyncio
import can
import pytest
from can.listener import AsyncBufferedReader
from can.notifier import Notifier


@pytest.mark.asyncio
async def test_roundtrip_virtual_bus_dual():
    # Two buses bound to the same virtual channel so RX sees TX without self-echo.
    tx_bus = can.Bus(interface="virtual", channel=0)
    rx_bus = can.Bus(interface="virtual", channel=0)

    reader = AsyncBufferedReader()
    notifier = Notifier(rx_bus, [reader])
    try:
        tx_bus.send(
            can.Message(arbitration_id=0x123, data=b"\xaa\xbb", is_extended_id=False)
        )
        msg = await asyncio.wait_for(reader.get_message(), timeout=1.0)
        assert msg.arbitration_id == 0x123
        assert bytes(msg.data) == b"\xaa\xbb"
    finally:
        notifier.stop()
        rx_bus.shutdown()
        tx_bus.shutdown()
