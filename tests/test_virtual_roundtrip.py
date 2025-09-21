# tests/test_virtual_roundtrip.py
import asyncio
import can
from can.notifier import Notifier
from can.listener import AsyncBufferedReader
import pytest


@pytest.mark.asyncio
async def test_roundtrip_virtual_bus_dual():
    tx_bus = can.Bus(interface="virtual", channel=0)
    rx_bus = can.Bus(interface="virtual", channel=0)

    reader = AsyncBufferedReader()
    notifier = Notifier(rx_bus, [reader])
    try:
        tx_bus.send(
            can.Message(arbitration_id=0x123, data=b"\xaa\xbb", is_extended_id=False)
        )
        # Give the notifier thread a scheduling tick to enqueue:
        await asyncio.sleep(0)
        msg = await asyncio.wait_for(reader.get_message(), timeout=2.0)
        assert msg.arbitration_id == 0x123
        assert bytes(msg.data) == b"\xaa\xbb"
    finally:
        notifier.stop()
        tx_bus.shutdown()
        rx_bus.shutdown()
