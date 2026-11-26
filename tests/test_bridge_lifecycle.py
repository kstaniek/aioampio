"""Exercise the bridge lifecycle with virtual CAN and controlled backend failures."""

import asyncio
from collections.abc import Callable
import threading
from unittest.mock import AsyncMock, Mock

import can
import pytest

from aioampio import AmpioBridge, AmpioTransmissionError
from aioampio import bridge as bridge_module
from aioampio.bridge_config import BridgeConfig
from aioampio.state_machine import ConnectionState


def make_bridge(**settings: object) -> AmpioBridge:
    """Use short, deterministic retries without idle watchdog reconnects."""
    config = BridgeConfig(
        read_timeout_s=0.01,
        reconnect_initial_s=0.01,
        reconnect_max_s=0.01,
        idle_reconnect_s=None,
        rx_gap_reconnect_s=None,
        max_no_rx_after_connect_s=None,
        **settings,
    )
    return AmpioBridge(
        {}, interface="virtual", channel="lifecycle-test", bridge_config=config
    )


async def wait_until(predicate: Callable[[], bool]) -> None:
    """Wait for observable progress with a finite deadline."""
    async with asyncio.timeout(3):
        while not predicate():
            await asyncio.sleep(0.001)


async def test_reconnect_replaces_bus_and_resumes_rx(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Keep the transport alive through manual reconnect and process new frames."""
    bridge = make_bridge()
    processed: list[int] = []

    async def on_frame(msg: can.Message) -> None:
        processed.append(msg.arbitration_id)

    monkeypatch.setattr(bridge, "_on_frame", on_frame)
    await bridge.start()
    try:
        assert await bridge.wait_connected(2)
        first_bus = bridge._bus
        bridge.trigger_reconnect("test")
        await wait_until(lambda: bridge.connected and bridge._bus is not first_bus)
        assert bridge._transport is not None and not bridge._transport.done()
        assert bridge.metrics.reconnects == 1
        tx = can.Bus(interface="virtual", channel="lifecycle-test")
        try:
            tx.send(can.Message(arbitration_id=123, data=b"x", is_extended_id=True))
            await wait_until(lambda: processed == [123])
        finally:
            tx.shutdown()
    finally:
        await bridge.stop()
    assert bridge.connection_state == ConnectionState.STOPPED
    assert bridge._bus is None
    assert bridge._rx_worker_manager is None


async def test_start_stop_are_repeatable_and_serialized() -> None:
    """Reuse one bridge and allow duplicate concurrent lifecycle requests."""
    bridge = make_bridge()
    for _ in range(2):
        await asyncio.gather(bridge.start(), bridge.start())
        assert await bridge.wait_connected(2)
        await asyncio.gather(bridge.stop(), bridge.stop())
        await bridge.stop()
        assert bridge.connection_state == ConnectionState.STOPPED
        assert not bridge.connected
        assert not await bridge.wait_connected(0.001)
        assert bridge._transport is None


async def test_failed_connection_retries(monkeypatch: pytest.MonkeyPatch) -> None:
    """Recover after one backend connection failure and count it once."""
    create_bus = can.Bus
    calls = 0

    def create(**kwargs: object) -> can.BusABC:
        nonlocal calls
        calls += 1
        if calls == 1:
            raise can.CanError("Simulated connection failure")
        return create_bus(**kwargs)

    monkeypatch.setattr(can, "Bus", create)
    bridge = make_bridge()
    await bridge.start()
    try:
        assert await bridge.wait_connected(2)
        assert calls == 2
        assert bridge.metrics.reconnects == 1
    finally:
        await bridge.stop()


async def test_permission_failure_leaves_truthful_state(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Stop retrying a permanent permission failure and clear connection state."""
    monkeypatch.setattr(can, "Bus", Mock(side_effect=PermissionError("Denied")))
    bridge = make_bridge()
    await bridge.start()
    await wait_until(lambda: bridge._transport.done())
    assert bridge._transport.exception() is None
    assert not bridge.connected
    assert bridge.connection_state == ConnectionState.DISCONNECTED
    await bridge.stop()


async def test_notifier_setup_failure_closes_bus_and_retries(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Close a constructed bus if session setup fails before receiving frames."""
    create_bus = can.Bus
    create_notifier = can.Notifier
    buses: list[can.BusABC] = []

    def create(**kwargs: object) -> can.BusABC:
        bus = create_bus(**kwargs)
        buses.append(bus)
        return bus

    def notifier(*args: object) -> can.Notifier:
        if len(buses) == 1:
            raise can.CanError("Simulated notifier failure")
        return create_notifier(*args)

    monkeypatch.setattr(can, "Bus", create)
    monkeypatch.setattr(can, "Notifier", notifier)
    bridge = make_bridge()
    await bridge.start()
    try:
        assert await bridge.wait_connected(2)
        assert len(buses) == 2
        assert buses[0]._is_shutdown
        assert bridge._bus is buses[1]
        assert bridge.metrics.reconnects == 1
    finally:
        await bridge.stop()


async def test_worker_failure_reconnects_using_configured_limit(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Recover a dead processing worker rather than leave a connected stale bridge."""
    bridge = make_bridge(max_consecutive_rx_errors=2)
    calls = 0

    async def on_frame(_msg: can.Message) -> None:
        nonlocal calls
        calls += 1
        if calls <= 2:
            raise ValueError("Simulated processing failure")

    monkeypatch.setattr(bridge, "_on_frame", on_frame)
    await bridge.start()
    try:
        assert await bridge.wait_connected(2)
        first_bus = bridge._bus
        for _ in range(2):
            bridge._proc_queue.put_nowait(can.Message(arbitration_id=1))
        await wait_until(lambda: bridge.connected and bridge._bus is not first_bus)
        bridge._proc_queue.put_nowait(can.Message(arbitration_id=2))
        await wait_until(lambda: calls == 3)
        assert bridge._rx_worker_manager.is_running
        assert bridge.metrics.reconnects == 1
    finally:
        await bridge.stop()


@pytest.mark.parametrize("cancel_send", [False, True])
async def test_shutdown_waits_for_inflight_send(
    monkeypatch: pytest.MonkeyPatch, cancel_send: bool
) -> None:
    """Do not close a bus while an executor send still uses it, including cancellation."""
    entered = threading.Event()
    release = threading.Event()
    bus = Mock(spec=can.BusABC)
    notifier = Mock()
    loop_thread = threading.get_ident()

    def send(*_args: object) -> None:
        entered.set()
        assert release.wait(3)

    def shutdown() -> None:
        assert threading.get_ident() != loop_thread

    bus.send.side_effect = send
    bus.shutdown.side_effect = shutdown
    notifier.stop.side_effect = shutdown
    monkeypatch.setattr(can, "Bus", Mock(return_value=bus))
    monkeypatch.setattr(can, "Notifier", Mock(return_value=notifier))
    bridge = make_bridge()
    await bridge.start()
    assert await bridge.wait_connected(2)
    sending = asyncio.create_task(bridge.send(123, b"x"))
    stopping = None
    try:
        await wait_until(entered.is_set)
        if cancel_send:
            sending.cancel()
        stopping = asyncio.create_task(bridge.stop())
        await wait_until(bridge._stop_event.is_set)
        await asyncio.sleep(0.01)
        assert not sending.done()
        assert not stopping.done()
        bus.shutdown.assert_not_called()
    finally:
        release.set()
        if cancel_send:
            with pytest.raises(asyncio.CancelledError):
                await sending
        else:
            await sending
        if stopping:
            await stopping
        else:
            await bridge.stop()
    bus.shutdown.assert_called_once_with()
    notifier.stop.assert_called_once_with()


async def test_queued_send_does_not_keep_a_stale_bus() -> None:
    """Select the current bus after acquiring the lifecycle-shared TX lock."""
    bridge = make_bridge()
    old_bus = Mock(spec=can.BusABC)
    current_bus = Mock(spec=can.BusABC)
    bridge._bus = old_bus
    async with bridge._bus_lock:
        sending = asyncio.create_task(bridge.send(123, b"x"))
        await asyncio.sleep(0)
        bridge._bus = current_bus
    await sending
    old_bus.send.assert_not_called()
    current_bus.send.assert_called_once()


async def test_queued_send_is_dropped_when_reconnect_starts() -> None:
    """Recheck reconnect status after waiting for the bus lock."""
    bridge = make_bridge()
    bus = Mock(spec=can.BusABC)
    bridge._bus = bus
    async with bridge._bus_lock:
        sending = asyncio.create_task(bridge.send(123, b"x"))
        await asyncio.sleep(0)
        bridge.trigger_reconnect("test")
    with pytest.raises(AmpioTransmissionError):
        await sending
    bus.send.assert_not_called()


async def test_receive_failure_blocks_tx_during_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A failing session must reject sends before asynchronous cleanup completes."""
    failed = asyncio.Event()
    cleaning = asyncio.Event()
    release = asyncio.Event()
    bus = Mock(spec=can.BusABC)
    reader = Mock()

    async def receive() -> None:
        await failed.wait()
        raise can.CanError("Simulated receive failure")

    reader.get = AsyncMock(side_effect=receive)
    monkeypatch.setattr(can, "Bus", Mock(return_value=bus))
    monkeypatch.setattr(can, "Notifier", Mock())
    monkeypatch.setattr(
        bridge_module, "BoundedAsyncCanReader", Mock(return_value=reader)
    )
    bridge = make_bridge()
    stop_workers = bridge._stop_rx_workers

    async def cleanup() -> None:
        cleaning.set()
        await release.wait()
        await stop_workers()

    monkeypatch.setattr(bridge, "_stop_rx_workers", cleanup)
    await bridge.start()
    try:
        assert await bridge.wait_connected(2)
        failed.set()
        await asyncio.wait_for(cleaning.wait(), 2)
        assert bridge.connection_state == ConnectionState.RECONNECTING
        assert not bridge.connected
        with pytest.raises(AmpioTransmissionError):
            await bridge.send(123, b"x")
        bus.send.assert_not_called()
    finally:
        release.set()
        await bridge.stop()


async def test_cancelled_stop_still_finishes_cleanup(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A cancelled stop caller must not interrupt resource cleanup."""
    entered = threading.Event()
    release = threading.Event()
    bus = Mock(spec=can.BusABC)

    def create(**_kwargs: object) -> can.BusABC:
        entered.set()
        assert release.wait(3)
        return bus

    monkeypatch.setattr(can, "Bus", create)
    bridge = make_bridge()
    await bridge.start()
    await wait_until(entered.is_set)
    stopping = asyncio.create_task(bridge.stop())
    await wait_until(bridge._stop_event.is_set)
    stopping.cancel()
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await stopping
    bus.shutdown.assert_called_once_with()
    assert bridge.connection_state == ConnectionState.STOPPED
    assert bridge._transport is None
