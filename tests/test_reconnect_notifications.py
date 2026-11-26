"""Retry-count notifications are immediate and independent of consumers."""

import asyncio
from unittest.mock import AsyncMock, Mock

from aioampio import AmpioBridge


async def test_reconnect_notification_precedes_backoff() -> None:
    """A failed connection publishes its count on the bridge event loop."""
    bridge = AmpioBridge({}, interface="virtual", channel="notification-test")
    await bridge.initialize()
    bridge._create_bus = AsyncMock(side_effect=OSError("unreachable"))
    observed: list[tuple[int, int, asyncio.AbstractEventLoop]] = []
    notified = asyncio.Event()

    def changed(count: int) -> None:
        observed.append((count, bridge.metrics.reconnects, asyncio.get_running_loop()))
        notified.set()

    unsubscribe = bridge.subscribe_reconnects(changed)
    assert not observed
    bridge._next_backoff = Mock(return_value=60)
    try:
        await bridge.start()
        await asyncio.wait_for(notified.wait(), timeout=1)
        assert observed == [(1, 1, asyncio.get_running_loop())]
        bridge._next_backoff.assert_called_once_with(0)
    finally:
        await bridge.stop()
        unsubscribe()
    assert len(observed) == 1
    assert not bridge._reconnect_listeners


def test_subscriptions_are_independent_and_unsubscribe_is_idempotent() -> None:
    """Duplicate callbacks have independent subscription lifetimes."""
    bridge = AmpioBridge({}, interface="virtual", channel="notification-test")
    changed = Mock()
    remove_first = bridge.subscribe_reconnects(changed)
    remove_second = bridge.subscribe_reconnects(changed)
    bridge._record_reconnect()
    assert changed.call_count == 2
    changed.assert_called_with(1)
    remove_first()
    remove_first()
    bridge._record_reconnect()
    assert changed.call_count == 3
    changed.assert_called_with(2)
    remove_second()
    bridge._record_reconnect()
    assert changed.call_count == 3
    assert bridge.metrics.reconnects == 3


def test_failing_subscriber_does_not_interrupt_other_consumers() -> None:
    """A consumer failure cannot prevent transport recovery or other notifications."""
    bridge = AmpioBridge({}, interface="virtual", channel="notification-test")
    broken = Mock(side_effect=RuntimeError("consumer failed"))
    healthy = Mock()
    bridge.subscribe_reconnects(broken)
    bridge.subscribe_reconnects(healthy)
    bridge._record_reconnect()
    assert bridge.metrics.reconnects == 1
    healthy.assert_called_once_with(1)


def test_callback_can_remove_itself() -> None:
    """A callback can unsubscribe safely while other consumers are notified."""
    bridge = AmpioBridge({}, interface="virtual", channel="notification-test")
    healthy = Mock()

    def changed(count: int) -> None:
        unsubscribe()

    unsubscribe = bridge.subscribe_reconnects(changed)
    bridge.subscribe_reconnects(healthy)
    bridge._record_reconnect()
    bridge._record_reconnect()
    assert healthy.call_count == 2
    healthy.assert_called_with(2)
