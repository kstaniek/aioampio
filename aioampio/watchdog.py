"""Watchdog system for detecting connection issues.

This module implements a flexible watchdog system for monitoring CAN bus
connection health. Multiple watchdogs can run concurrently, each monitoring
different aspects of the connection.

Watchdog Types:
    NotifierStallWatchdog: Detects when notifier connects but delivers no messages
    RxGapWatchdog: Detects gaps in message reception after initial messages
    IdleWatchdog: Detects extended periods of no activity (fallback watchdog)

The watchdog system provides:
- Multiple concurrent monitors for different failure modes
- Configurable timeouts for each watchdog type
- Unified triggering via reconnect event
- Clean separation of concerns (each watchdog has one job)

Architecture:
    Each watchdog independently monitors specific conditions and can trigger
    a reconnection event. The WatchdogManager coordinates checking all watchdogs
    and provides a single interface for the bridge.

Example:
    >>> manager = WatchdogManager()
    >>> manager.add_watchdog(
    ...     NotifierStallWatchdog(logger, reconnect_event, timeout_s=10.0)
    ... )
    >>> manager.add_watchdog(
    ...     RxGapWatchdog(logger, reconnect_event, timeout_s=15.0)
    ... )
    >>> # Later, check all watchdogs
    >>> triggered = manager.check_all(now, connected_since, last_rx)

Classes:
    Watchdog: Abstract base class for all watchdogs
    NotifierStallWatchdog: Detects notifier stall (no initial messages)
    RxGapWatchdog: Detects gaps in message flow
    IdleWatchdog: Detects extended idle periods (fallback)
    WatchdogManager: Coordinates multiple watchdog instances
"""

import asyncio
from abc import ABC, abstractmethod
import logging


class Watchdog(ABC):
    """Base class for watchdog timers that detect connection issues.

    Watchdogs monitor various aspects of the connection and signal when
    a reconnect should be triggered. Each watchdog focuses on one specific
    failure mode and operates independently.

    The check() method is called periodically (typically on message read timeout)
    and should return True if the watchdog condition is triggered.

    Subclasses must implement:
        check(now, connected_since, last_rx) -> bool

    Attributes:
        logger: Logger for watchdog messages
        _reconnect_event: Event to set when reconnect is needed
    """

    def __init__(
        self,
        logger: logging.Logger,
        reconnect_event: asyncio.Event,
    ) -> None:
        """Initialize watchdog.

        Args:
            logger: Logger for watchdog messages
            reconnect_event: Event to set when reconnect is needed
        """
        self.logger = logger
        self._reconnect_event = reconnect_event

    @abstractmethod
    def check(
        self,
        now: float,
        connected_since: float | None,
        last_rx: float | None,
    ) -> bool:
        """Check if watchdog condition is triggered.

        Args:
            now: Current monotonic time
            connected_since: Time of connection establishment (None if not connected)
            last_rx: Time of last received message (None if no messages received)

        Returns:
            True if reconnect should be triggered
        """

    def trigger_reconnect(self, reason: str, duration: float) -> None:
        """Trigger reconnect and log the reason.

        Args:
            reason: Description of why reconnect is triggered
            duration: Time duration that triggered the watchdog (seconds)
        """
        self.logger.warning("%s (%.0fs)", reason, duration)
        self._reconnect_event.set()


class NotifierStallWatchdog(Watchdog):
    """Detects when no RX messages arrive after connection.

    This watchdog detects "notifier stall" - when the CAN notifier connects
    but never delivers any messages, indicating a problem with the notifier.
    """

    def __init__(
        self,
        logger: logging.Logger,
        reconnect_event: asyncio.Event,
        timeout_s: float,
    ) -> None:
        """Initialize notifier stall watchdog.

        Args:
            logger: Logger for watchdog messages
            reconnect_event: Event to set when reconnect is needed
            timeout_s: Timeout in seconds after connect with no RX
        """
        super().__init__(logger, reconnect_event)
        self.timeout_s = timeout_s

    def check(
        self,
        now: float,
        connected_since: float | None,
        last_rx: float | None,
    ) -> bool:
        """Check if no RX received after connection timeout.

        Args:
            now: Current monotonic time
            connected_since: Time of connection establishment
            last_rx: Time of last received message (None = no messages yet)

        Returns:
            True if timeout exceeded with no RX after connect
        """
        if last_rx is not None:
            return False  # Already received messages, no stall

        if connected_since is None:
            return False  # Not connected yet

        since_connect = now - connected_since
        if since_connect >= self.timeout_s:
            self.trigger_reconnect(
                "No RX within timeout after connect; forcing reconnect (notifier stall?)",
                since_connect,
            )
            return True

        return False


class RxGapWatchdog(Watchdog):
    """Detects when RX messages stop arriving after initial reception.

    This watchdog triggers when we've received messages before, but then
    see no messages for an extended period, indicating a connection problem.
    """

    def __init__(
        self,
        logger: logging.Logger,
        reconnect_event: asyncio.Event,
        timeout_s: float,
    ) -> None:
        """Initialize RX gap watchdog.

        Args:
            logger: Logger for watchdog messages
            reconnect_event: Event to set when reconnect is needed
            timeout_s: Maximum gap in seconds between RX messages
        """
        super().__init__(logger, reconnect_event)
        self.timeout_s = timeout_s

    def check(
        self,
        now: float,
        connected_since: float | None,
        last_rx: float | None,
    ) -> bool:
        """Check if RX gap timeout exceeded.

        Args:
            now: Current monotonic time
            connected_since: Time of connection establishment (unused)
            last_rx: Time of last received message

        Returns:
            True if RX gap timeout exceeded
        """
        if last_rx is None:
            return False  # No messages yet, not a gap

        gap = now - last_rx
        if gap >= self.timeout_s:
            self.trigger_reconnect(
                "No RX since last message; forcing reconnect (rx-gap watchdog)",
                gap,
            )
            return True

        return False


class IdleWatchdog(Watchdog):
    """Detects when connection is idle for too long.

    This watchdog triggers when no RX activity for an extended period,
    either since connection or since last message. This is the fallback
    watchdog that catches long-term connection issues.
    """

    def __init__(
        self,
        logger: logging.Logger,
        reconnect_event: asyncio.Event,
        timeout_s: float,
    ) -> None:
        """Initialize idle watchdog.

        Args:
            logger: Logger for watchdog messages
            reconnect_event: Event to set when reconnect is needed
            timeout_s: Maximum idle time in seconds
        """
        super().__init__(logger, reconnect_event)
        self.timeout_s = timeout_s

    def check(
        self,
        now: float,
        connected_since: float | None,
        last_rx: float | None,
    ) -> bool:
        """Check if idle timeout exceeded.

        Args:
            now: Current monotonic time
            connected_since: Time of connection establishment
            last_rx: Time of last received message

        Returns:
            True if idle timeout exceeded
        """
        # Calculate base time: last RX or connect time
        base = last_rx if last_rx is not None else connected_since
        if base is None:
            return False
        idle = max(0.0, now - base)

        if idle >= self.timeout_s:
            self.trigger_reconnect(
                "No RX for extended period; forcing reconnect (idle watchdog)",
                idle,
            )
            return True

        return False


class WatchdogManager:
    """Manages multiple watchdog instances.

    Coordinates checking all enabled watchdogs and provides a unified
    interface for the bridge to use.
    """

    def __init__(self) -> None:
        """Initialize watchdog manager."""
        self._watchdogs: list[Watchdog] = []

    def add_watchdog(self, watchdog: Watchdog) -> None:
        """Add a watchdog to the manager.

        Args:
            watchdog: Watchdog instance to add
        """
        self._watchdogs.append(watchdog)

    def check_all(
        self,
        now: float,
        connected_since: float | None,
        last_rx: float | None,
    ) -> bool:
        """Check all watchdogs.

        Args:
            now: Current monotonic time
            connected_since: Time of connection establishment
            last_rx: Time of last received message

        Returns:
            True if any watchdog triggered
        """
        return any(
            watchdog.check(now, connected_since, last_rx)
            for watchdog in self._watchdogs
        )

    def is_enabled(self) -> bool:
        """Check if any watchdogs are enabled.

        Returns:
            True if at least one watchdog is active
        """
        return len(self._watchdogs) > 0
