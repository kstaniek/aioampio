"""Exercise traffic accounting independently of Home Assistant."""

import asyncio
from datetime import UTC, datetime
import threading
import time
from unittest.mock import Mock

import can
import pytest

from aioampio import AmpioBridge, AmpioTransmissionError
from aioampio.bridge_config import BridgeConfig
from aioampio.helpers.rx_reader import BoundedAsyncCanReader
from aioampio.module_metrics import ModuleTraffic
from aioampio.controllers.utils import generate_multican_payload

CFG = {
    "devices": [
        {"can_id": 0x123, "model": 4, "name": "One"},
        {"can_id": 0x124, "model": 4, "name": "Two"},
    ]
}


def frame(**kwargs) -> can.Message:
    return can.Message(
        **{
            "arbitration_id": 0x123,
            "data": b"\xfe\xff",
            "is_extended_id": True,
            **kwargs,
        }
    )


@pytest.mark.parametrize(
    "changes",
    [
        {"arbitration_id": 0x125},
        {"is_extended_id": False},
        {"is_remote_frame": True},
        {"is_error_frame": True},
        {"data": b""},
        {"dlc": 5},
    ],
)
def test_invalid_or_unconfigured_sources_do_not_count(changes: dict) -> None:
    traffic = ModuleTraffic([0x123])
    traffic.receive(frame(**changes), time.monotonic())
    assert traffic.snapshot()[0x123].rx_total == 0


async def test_ingress_counts_repeated_undecodable_frames_before_drops() -> None:
    traffic = ModuleTraffic([0x123])
    reader = BoundedAsyncCanReader(
        asyncio.get_running_loop(), maxsize=1, on_receive=traffic.receive
    )
    for _ in range(3):
        reader.listener.on_message_received(frame())
    await asyncio.sleep(0)
    assert reader.qsize() == 1
    assert traffic.snapshot()[0x123].rx_total == 3
    assert traffic.snapshot()[0x123].last_rx_age_s is not None
    snapshot = traffic.snapshot()
    snapshot.clear()
    assert traffic.snapshot()[0x123].rx_total == 3
    traffic.reset_session()
    assert traffic.snapshot()[0x123].rx_total == 3
    assert traffic.snapshot()[0x123].last_rx_age_s is None


async def test_bridge_attributes_successful_frames_to_destinations() -> None:
    bridge = AmpioBridge(CFG, interface="virtual", channel="metrics")
    await bridge.initialize()
    bus = Mock(spec=can.BusABC)
    bridge._bus = bus
    await bridge.send(0x0F000000, bytes.fromhex("00000123150100"))
    fragments = generate_multican_payload(0x124, b"long payload")
    for payload in fragments:
        await bridge.send(0x0F000000, payload)
    await bridge.send(0x123, b"x")  # Not an Ampio addressed command.
    assert bridge.module_metrics[0x123].tx_total == 1
    assert bridge.module_metrics[0x124].tx_total == len(fragments)
    bus.send.side_effect = can.CanError("send failed")
    with pytest.raises(AmpioTransmissionError):
        await bridge.send(0x0F000000, bytes.fromhex("00000123150100"))
    bridge._bus = None
    with pytest.raises(AmpioTransmissionError):
        await bridge.send(0x0F000000, bytes.fromhex("00000123150100"))
    assert bridge.module_metrics[0x123].tx_total == 1
    assert bridge.module_metrics[0x123].last_rx_age_s is None


@pytest.mark.parametrize("fail", [False, True])
async def test_cancelled_send_accounts_for_actual_completion(fail: bool) -> None:
    bridge = AmpioBridge(CFG, interface="virtual", channel="metrics")
    await bridge.initialize()
    entered = threading.Event()
    release = threading.Event()

    def send(*args) -> None:
        entered.set()
        assert release.wait(3)
        if fail:
            raise can.CanError("failed after cancellation")

    bridge._bus = Mock(spec=can.BusABC, send=send)
    task = asyncio.create_task(bridge.send(0x0F000000, bytes.fromhex("00000123150100")))
    try:
        async with asyncio.timeout(2):
            while not entered.is_set():
                await asyncio.sleep(0.001)
        task.cancel()
        await asyncio.sleep(0)
    finally:
        release.set()
        with pytest.raises(asyncio.CancelledError):
            await task
    assert bridge.module_metrics[0x123].tx_total == (0 if fail else 1)
    assert bridge.metrics.tx_total == (0 if fail else 1)
    assert bridge.metrics.tx_errors == (1 if fail else 0)


async def test_silence_does_not_reconnect_but_transport_errors_do() -> None:
    bridge = AmpioBridge(
        CFG,
        interface="virtual",
        channel="metrics",
        bridge_config=BridgeConfig(read_timeout_s=0.01),
    )
    await bridge.initialize()
    await bridge.start()
    try:
        assert await bridge.wait_connected(2)
        bus = bridge._bus
        bridge._connected_since_mono = time.monotonic() - 1000
        bridge._last_rx_mono = time.monotonic() - 1000
        await asyncio.sleep(0.05)
        assert bridge.connected
        assert bridge._bus is bus
        assert bridge.metrics.reconnects == 0
        bridge.trigger_reconnect("transport error")
        async with asyncio.timeout(2):
            while bridge.metrics.reconnects == 0:
                await asyncio.sleep(0.001)
        assert bridge.metrics.reconnects == 1
    finally:
        await bridge.stop()


async def test_socket_eof_recovers_without_silence_watchdog() -> None:
    async def close_socket(reader, writer) -> None:
        writer.close()
        await writer.wait_closed()

    server = await asyncio.start_server(close_socket, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    bridge = AmpioBridge(
        CFG,
        interface="waveshare",
        channel="can0",
        host="127.0.0.1",
        port=port,
        bridge_config=BridgeConfig(read_timeout_s=0.02, reconnect_initial_s=0.01),
    )
    await bridge.initialize()
    try:
        await bridge.start()
        async with asyncio.timeout(3):
            while bridge.metrics.reconnects == 0:
                await asyncio.sleep(0.01)
    finally:
        await bridge.stop()
        server.close()
        await server.wait_closed()


async def test_live_rx_counts_repeat_frames_and_preserves_totals_on_reconnect() -> None:
    """Exercise the real notifier-to-reader bridge path over virtual CAN."""
    bridge = AmpioBridge(
        CFG,
        interface="virtual",
        channel="module-ingress",
        bridge_config=BridgeConfig(read_timeout_s=0.01, reconnect_initial_s=0.01),
    )
    await bridge.initialize()
    tx = can.Bus(interface="virtual", channel="module-ingress")
    try:
        await bridge.start()
        assert await bridge.wait_connected(2)
        for _ in range(3):
            tx.send(frame())
        async with asyncio.timeout(2):
            while bridge.module_metrics[0x123].rx_total < 3:
                await asyncio.sleep(0.001)
        assert bridge.module_metrics[0x124].rx_total == 0
        assert bridge.module_metrics[0x123].last_rx_age_s is not None
        old_session = bridge.metrics.session_id
        bridge.trigger_reconnect("test transport recovery")
        async with asyncio.timeout(3):
            while not bridge.connected or bridge.metrics.session_id == old_session:
                await asyncio.sleep(0.001)
        assert bridge.module_metrics[0x123].rx_total == 3
        assert bridge.module_metrics[0x123].last_rx_age_s is None
        tx.send(frame())
        async with asyncio.timeout(2):
            while bridge.module_metrics[0x123].rx_total < 4:
                await asyncio.sleep(0.001)
        assert bridge.module_metrics[0x123].last_rx_age_s is not None
    finally:
        tx.shutdown()
        await bridge.stop()


def test_timestamp_survives_idle_and_reconnect() -> None:
    """Last received is an actual reception instant, not the time of reading it."""
    traffic = ModuleTraffic([0x123])
    assert traffic.snapshot()[0x123].last_rx_at is None
    stamp = datetime(2026, 11, 26, 10, 20, 30, tzinfo=UTC)
    traffic.receive(frame(), time.monotonic(), stamp)
    assert traffic.snapshot()[0x123].last_rx_at == stamp
    traffic.reset_session()
    assert traffic.snapshot()[0x123].last_rx_age_s is None
    assert traffic.snapshot()[0x123].last_rx_at == stamp
    assert traffic.snapshot()[0x123].rx_total == 1


async def test_gateway_timestamp_captures_ingress() -> None:
    """Global timing covers all ingress independently of configured source totals."""
    bridge = AmpioBridge(CFG, interface="virtual", channel="timestamps")
    await bridge.initialize()
    assert bridge.metrics.last_rx_at is None
    before = datetime.now(UTC)
    bridge._on_rx_received(frame(arbitration_id=0x125), time.monotonic())
    stamp = bridge.metrics.last_rx_at
    assert before <= stamp <= datetime.now(UTC)
    assert all(module.last_rx_at is None for module in bridge.module_metrics.values())
    assert bridge.metrics.to_dict()["last_rx_at"] == stamp.isoformat()
    bridge._reset_connect_state()
    assert bridge.metrics.last_rx_at == stamp
    bridge._on_rx_received(frame(), time.monotonic())
    assert bridge.module_metrics[0x123].last_rx_at == bridge.metrics.last_rx_at
