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
        # Let the notifier’s background thread fully start
        await asyncio.sleep(0.05)

        tx_bus.send(
            can.Message(arbitration_id=0x123, data=b"\xaa\xbb", is_extended_id=False)
        )

        # Poll in short slices to avoid flakiness from thread->loop marshaling
        msg = None
        for _ in range(20):  # up to ~2.0s total
            try:
                msg = await asyncio.wait_for(reader.get_message(), timeout=0.1)
                break
            except asyncio.TimeoutError:
                # Yield once to let call_soon_threadsafe callbacks run
                await asyncio.sleep(0)

        assert msg is not None, "Timed out waiting for message from virtual bus"
        assert msg.arbitration_id == 0x123
        assert bytes(msg.data) == b"\xaa\xbb"
    finally:
        notifier.stop()
        tx_bus.shutdown()
        rx_bus.shutdown()
