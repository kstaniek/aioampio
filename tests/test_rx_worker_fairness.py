"""Ensure queued CAN bursts do not monopolize the asyncio event loop."""

import asyncio
from types import SimpleNamespace

import can
import pytest

from aioampio import AmpioBridge
from aioampio import bridge as bridge_module


def make_bridge() -> AmpioBridge:
    """Use keyword arguments supported by main and the 1.0.x maintenance API."""
    return AmpioBridge(
        cfg={}, interface="virtual", channel="rx-test", host="127.0.0.1", port=0
    )


@pytest.mark.parametrize(
    ("frame_time", "workers", "fails", "expected_batch"),
    [
        pytest.param(0.0, 1, False, 16, id="frame-count-budget"),
        pytest.param(0.006, 1, False, 2, id="time-budget"),
        pytest.param(0.0, 2, False, 32, id="multiple-workers"),
        pytest.param(0.0, 1, True, 16, id="errors-frame-budget"),
        pytest.param(0.006, 1, True, 2, id="errors-time-budget"),
    ],
)
async def test_burst_yields_without_losing_frames(
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
    frame_time: float,
    workers: int,
    fails: bool,
    expected_batch: int,
) -> None:
    """Allow competing tasks to run while retaining FIFO order and all frames."""
    bridge = make_bridge()
    total = 80
    processed: list[int] = []
    heartbeat: list[int] = []
    finished = asyncio.Event()
    now = 0.0

    def monotonic() -> float:
        return now

    async def on_frame(message: can.Message) -> None:
        nonlocal now
        processed.append(message.arbitration_id)
        now += frame_time
        if len(processed) == total:
            finished.set()
        if fails:
            raise ValueError("Simulated frame error")

    monkeypatch.setattr(bridge_module, "time", SimpleNamespace(monotonic=monotonic))
    monkeypatch.setattr(bridge, "_on_frame", on_frame)
    for identifier in range(total):
        bridge._proc_queue.put_nowait(can.Message(arbitration_id=identifier))

    bridge._start_rx_workers(n=workers)
    asyncio.get_running_loop().call_soon(lambda: heartbeat.append(len(processed)))
    try:
        async with asyncio.timeout(2):
            await finished.wait()
        assert heartbeat == [expected_batch]
        assert processed == list(range(total))
        assert bridge._rx_total == total
        assert bridge._proc_queue.empty()
        failures = [
            record for record in caplog.records if record.name == bridge.logger.name
        ]
        assert len(failures) == (total if fails else 0)
    finally:
        await bridge._stop_rx_workers()


async def test_stop_can_interrupt_a_backlog(monkeypatch: pytest.MonkeyPatch) -> None:
    """Cancel workers promptly rather than draining a full receive backlog."""
    bridge = make_bridge()
    processed: list[int] = []

    async def on_frame(message: can.Message) -> None:
        processed.append(message.arbitration_id)

    monkeypatch.setattr(bridge_module, "time", SimpleNamespace(monotonic=lambda: 0.0))
    monkeypatch.setattr(bridge, "_on_frame", on_frame)
    for identifier in range(80):
        bridge._proc_queue.put_nowait(can.Message(arbitration_id=identifier))

    bridge._start_rx_workers()
    task = asyncio.create_task(bridge._stop_rx_workers())
    await asyncio.wait_for(task, 2)
    assert processed == list(range(16))
    assert bridge._proc_queue.qsize() == 64
    assert not bridge._rx_workers


async def test_stop_event_is_respected(monkeypatch: pytest.MonkeyPatch) -> None:
    """Stop after the current frame when shutdown is requested by a callback."""
    bridge = make_bridge()
    processed: list[int] = []

    async def on_frame(message: can.Message) -> None:
        processed.append(message.arbitration_id)
        bridge._stop_event.set()

    monkeypatch.setattr(bridge, "_on_frame", on_frame)
    for identifier in range(80):
        bridge._proc_queue.put_nowait(can.Message(arbitration_id=identifier))

    bridge._start_rx_workers()
    try:
        await asyncio.wait_for(bridge._rx_workers[0], 2)
        assert processed == [0]
        assert bridge._proc_queue.qsize() == 79
    finally:
        await bridge._stop_rx_workers()
