"""Check watchdog deadlines and disabled/configuration edge cases."""

import asyncio
import logging

import pytest

from aioampio.bridge_config import BridgeConfig
from aioampio.watchdog import (
    IdleWatchdog,
    NotifierStallWatchdog,
    RxGapWatchdog,
    WatchdogManager,
)


@pytest.mark.parametrize("kind", [IdleWatchdog, NotifierStallWatchdog, RxGapWatchdog])
def test_deadline_includes_zero_timestamp(kind: type) -> None:
    """A monotonic origin of zero is valid, and the boundary triggers once reached."""
    reconnect = asyncio.Event()
    watchdog = kind(logging.getLogger("test"), reconnect, 10)
    last_rx = 0.0 if kind is RxGapWatchdog else None
    assert not watchdog.check(9.99, 0.0, last_rx)
    assert not reconnect.is_set()
    assert watchdog.check(10.0, 0.0, last_rx)
    assert reconnect.is_set()


@pytest.mark.parametrize("kind", [IdleWatchdog, NotifierStallWatchdog, RxGapWatchdog])
def test_no_activity_before_connection(kind: type) -> None:
    """No session means there is no idle deadline to expire."""
    event = asyncio.Event()
    assert not kind(logging.getLogger("test"), event, 1).check(100, None, None)
    assert not event.is_set()


def test_activity_resets_idle_and_disables_initial_stall() -> None:
    """First-message and rolling-gap watchdogs have different recovery semantics."""
    event = asyncio.Event()
    log = logging.getLogger("test")
    assert not NotifierStallWatchdog(log, event, 10).check(50, 0, 49)
    assert not RxGapWatchdog(log, event, 10).check(50, 0, 49)
    assert not IdleWatchdog(log, event, 10).check(50, 0, 49)


def test_manager_with_disabled_and_multiple_watchdogs() -> None:
    """An empty manager is inert; an enabled manager requests a reconnect."""
    event = asyncio.Event()
    manager = WatchdogManager()
    assert not manager.is_enabled()
    assert not manager.check_all(10, 0, None)
    manager.add_watchdog(NotifierStallWatchdog(logging.getLogger("test"), event, 10))
    manager.add_watchdog(IdleWatchdog(logging.getLogger("test"), event, 20))
    assert manager.is_enabled()
    assert manager.check_all(10, 0, None)
    assert event.is_set()


@pytest.mark.parametrize(
    "field",
    [
        "read_timeout_s",
        "reconnect_initial_s",
        "reconnect_max_s",
        "tx_timeout_s",
        "idle_reconnect_s",
        "rx_gap_reconnect_s",
        "max_no_rx_after_connect_s",
    ],
)
@pytest.mark.parametrize("value", [0, -1, float("nan"), float("inf")])
def test_invalid_timeout_is_rejected(field: str, value: float) -> None:
    """Reject timeouts that cannot produce a meaningful positive deadline."""
    with pytest.raises(ValueError, match=field):
        BridgeConfig(**{field: value})
