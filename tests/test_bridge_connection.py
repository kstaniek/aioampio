"""Regression tests for nonblocking CAN connection setup and cleanup."""

import asyncio
import threading
from unittest.mock import Mock

import can
import pytest

from aioampio import AmpioBridge


async def wait_for_thread(event: threading.Event) -> None:
    """Wait for a test worker without blocking the event loop."""
    async with asyncio.timeout(2):
        while not event.is_set():
            await asyncio.sleep(0.001)


async def test_connection_does_not_block_loop(monkeypatch: pytest.MonkeyPatch) -> None:
    """Allow event-loop progress while a blocking CAN constructor is pending."""
    entered = threading.Event()
    release = threading.Event()
    bus = Mock(spec=can.BusABC)
    loop_thread = threading.get_ident()
    bridge = AmpioBridge({}, interface="virtual", channel="test")

    def create_bus(**kwargs: object) -> can.BusABC:
        assert threading.get_ident() != loop_thread
        assert kwargs == {
            "interface": "virtual",
            "channel": "test",
            "host": "192.0.2.1",
        }
        entered.set()
        assert release.wait(2)
        return bus

    monkeypatch.setattr(can, "Bus", create_bus)
    task = asyncio.create_task(
        bridge._create_bus("virtual", "test", {"host": "192.0.2.1"})
    )
    try:
        await wait_for_thread(entered)
        assert not task.done()
    finally:
        release.set()
    assert await asyncio.wait_for(task, 2) is bus
    bus.shutdown.assert_not_called()


@pytest.mark.parametrize("fails", [False, True], ids=["connected", "connection-failed"])
async def test_cancelled_connection_cleanup(
    monkeypatch: pytest.MonkeyPatch, fails: bool
) -> None:
    """Close a late bus and preserve cancellation even if its constructor fails."""
    entered = threading.Event()
    release = threading.Event()
    closed = threading.Event()
    loop_thread = threading.get_ident()
    bridge = AmpioBridge({}, interface="virtual", channel="test")
    bus = Mock(spec=can.BusABC)

    def shutdown() -> None:
        assert threading.get_ident() != loop_thread
        closed.set()

    def create_bus(**_kwargs: object) -> can.BusABC:
        entered.set()
        assert release.wait(2)
        if fails:
            raise can.CanError("Simulated connection failure")
        return bus

    bus.shutdown.side_effect = shutdown
    monkeypatch.setattr(can, "Bus", create_bus)
    task = asyncio.create_task(bridge._create_bus("virtual", "test", {}))
    try:
        await wait_for_thread(entered)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(task, 2)
    assert closed.is_set() is not fails


async def test_connection_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    """Propagate backend errors to the existing reconnect handler."""
    bridge = AmpioBridge({}, interface="virtual", channel="test")
    monkeypatch.setattr(can, "Bus", Mock(side_effect=can.CanError("Simulated failure")))
    with pytest.raises(can.CanError, match="Simulated failure"):
        await bridge._create_bus("virtual", "test", {})


async def test_stop_during_connection(monkeypatch: pytest.MonkeyPatch) -> None:
    """Wait for a pending constructor and close its bus before stop returns."""
    entered = threading.Event()
    release = threading.Event()
    bus = Mock(spec=can.BusABC)
    bridge = AmpioBridge({}, interface="virtual", channel="test")

    def create_bus(**_kwargs: object) -> can.BusABC:
        entered.set()
        assert release.wait(2)
        return bus

    monkeypatch.setattr(can, "Bus", create_bus)
    await bridge.start()
    try:
        await wait_for_thread(entered)
        stop_task = asyncio.create_task(bridge.stop())
        await asyncio.sleep(0)
        assert not stop_task.done()
    finally:
        release.set()
    await asyncio.wait_for(stop_task, 2)
    bus.shutdown.assert_called_once_with()
    assert bridge._bus is None
    assert bridge._transport is None


async def test_virtual_start_stop() -> None:
    """Connect and stop twice without leaving a bus or transport behind."""
    bridge = AmpioBridge({}, interface="virtual", channel="release-test")
    for _ in range(2):
        await bridge.start()
        try:
            assert await bridge.wait_connected(timeout=2)
            assert bridge.connected
        finally:
            await bridge.stop()
        assert not bridge.connected
        assert bridge._bus is None
        assert bridge._transport is None
