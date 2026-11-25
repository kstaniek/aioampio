"""Check state notifications, concurrency, feedback, and cancellation."""

import asyncio
from unittest.mock import Mock

import pytest

from aioampio.controllers.events import EventType
from aioampio.state_store import StateStore


async def test_changes_deduplication_and_unsubscribe() -> None:
    """Notify global then topic listeners only when values change."""
    store = StateStore(Mock())
    received = []
    store.on_change(lambda event, data: received.append(("global", event, data)))
    remove = store.on_change(
        lambda event, data: received.append(("topic", event, data)), topic="a"
    )
    assert await store.set("a", {"value": 1})
    assert not await store.set("a", {"value": 1})
    assert [r[0] for r in received] == ["global", "topic"]
    assert received[0][1] == EventType.ENTITY_UPDATED
    assert received[0][2] == {"topic": "a", "data": {"value": 1}, "previous": None}
    remove()
    remove()
    assert await store.set("a", {"value": 2})
    assert received[-1][0] == "global"
    assert received[-1][2]["previous"] == {"value": 1}
    snapshot = store.snapshot()
    snapshot.clear()
    assert store.get("a") == {"value": 2}


async def test_callbacks_use_snapshot_and_isolate_errors() -> None:
    """Unsubscription during dispatch and one error must not skip other callbacks."""
    bridge = Mock()
    store = StateStore(bridge)
    received = []
    unsubscribe = Mock()

    def first(_event: EventType, _data: dict) -> None:
        unsubscribe()
        raise ValueError("Callback failure")

    store.on_change(first)
    unsubscribe = store.on_change(lambda _event, data: received.append(data))
    await store.set("a", 1)
    assert len(received) == 1
    bridge.logger.exception.assert_called_once()
    await store.set("a", 2)
    assert len(received) == 1


async def test_same_topic_notifications_are_ordered() -> None:
    """A slow async listener cannot allow a newer update to overtake its notification."""
    store = StateStore(Mock())
    entered = asyncio.Event()
    release = asyncio.Event()
    order = []

    async def slow(_event: EventType, data: dict) -> None:
        if data["data"] == 1:
            entered.set()
            await release.wait()
        order.append(data["data"])

    store.on_change(slow)
    store.on_change(lambda _event, data: order.append(-data["data"]))
    first = asyncio.create_task(store.set("a", 1))
    await entered.wait()
    second = asyncio.create_task(store.set("a", 2))
    await asyncio.sleep(0)
    assert not second.done()
    release.set()
    assert await first
    assert await second
    assert order == [1, -1, 2, -2]


async def test_feedback_is_deferred_without_deadlock() -> None:
    """A callback may update its own topic; other listeners still see ordered events."""
    store = StateStore(Mock())
    seen = []

    async def feedback(_event: EventType, data: dict) -> None:
        if data["data"] == 1:
            assert await store.set("a", 2)

    store.on_change(feedback)
    store.on_change(lambda _event, data: seen.append(data["data"]))
    assert await asyncio.wait_for(store.set("a", 1), 2)
    assert seen == [1, 2]
    assert store.get("a") == 2


async def test_cancelled_dispatch_releases_waiting_writers() -> None:
    """Cancellation cannot strand another writer or prevent subsequent delivery."""
    store = StateStore(Mock())
    entered = asyncio.Event()

    async def slow(_event: EventType, data: dict) -> None:
        if data["data"] == 1:
            entered.set()
            await asyncio.Event().wait()

    store.on_change(slow)
    first = asyncio.create_task(store.set("a", 1))
    await entered.wait()
    second = asyncio.create_task(store.set("a", 2))
    await asyncio.sleep(0)
    first.cancel()
    with pytest.raises(asyncio.CancelledError):
        await first
    with pytest.raises(asyncio.CancelledError):
        await asyncio.wait_for(second, 2)
    assert await store.set("a", 3)


async def test_nan_and_binary_payload_equality() -> None:
    """Repeated NaN and equivalent binary payloads do not generate endless updates."""
    store = StateStore(Mock())
    assert await store.set("number", float("nan"))
    assert not await store.set("number", float("nan"))
    assert await store.set("binary", b"abc")
    assert not await store.set("binary", bytearray(b"abc"))


async def test_different_topics_can_notify_concurrently() -> None:
    """A slow topic must not block delivery on another topic."""
    store = StateStore(Mock())
    entered = asyncio.Event()
    release = asyncio.Event()
    seen = []

    async def slow(_event: EventType, data: dict) -> None:
        if data["topic"] == "a":
            entered.set()
            await release.wait()
        seen.append(data["topic"])

    store.on_change(slow)
    first = asyncio.create_task(store.set("a", 1))
    await entered.wait()
    try:
        assert await asyncio.wait_for(store.set("b", 1), 2)
        assert seen == ["b"]
    finally:
        release.set()
        await first
    assert seen == ["b", "a"]


async def test_cross_topic_feedback_does_not_deadlock() -> None:
    """Callbacks that write back across topics retain per-topic delivery order."""
    store = StateStore(Mock())
    seen = []

    async def feedback(_event: EventType, data: dict) -> None:
        if data["topic"] == "a" and data["data"] == 1:
            await store.set("b", 1)
        elif data["topic"] == "b":
            await store.set("a", 2)

    store.on_change(feedback)
    store.on_change(lambda _event, data: seen.append((data["topic"], data["data"])))
    assert await asyncio.wait_for(store.set("a", 1), 2)
    assert seen == [("b", 1), ("a", 1), ("a", 2)]
