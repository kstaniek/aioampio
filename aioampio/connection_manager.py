"""Connection management for the Ampio bridge.

This module handles CAN bus connection lifecycle, including connection
establishment, session management, reconnection logic, and graceful shutdown.

The connection manager provides:
- Automatic reconnection with exponential backoff
- Session lifecycle management (setup, run, teardown)
- CAN filter application for device whitelists
- Error handling and recovery
- Clean shutdown on permission errors or critical failures

Classes:
    ConnectionManager: Manages CAN bus connection lifecycle
"""

import asyncio
from contextlib import suppress
import logging
import random
from typing import Any, Callable, Awaitable

import can

from aioampio.helpers.rx_reader import BoundedAsyncCanReader
from aioampio.state_machine import ConnectionState


class ConnectionManager:  # pylint: disable=too-many-instance-attributes
    """Manages CAN bus connection lifecycle with automatic reconnection.

    The connection manager handles establishing connections to the CAN bus,
    running sessions, and reconnecting on failures. It implements exponential
    backoff for reconnection attempts and provides hooks for session lifecycle events.

    Attributes:
        logger: Logger for connection messages
        interface: CAN interface backend name
        channel: CAN channel identifier
        bus_kwargs: Additional arguments for python-can Bus constructor
        initial_backoff_s: Initial reconnection delay (seconds)
        max_backoff_s: Maximum reconnection delay (seconds)
        read_timeout_s: Timeout for reading messages (seconds)
        bounded_reader_size: Size of the bounded message reader
    """

    def __init__(  # pylint: disable=too-many-arguments,too-many-locals
        self,
        logger: logging.Logger,
        interface: str,
        channel: str,
        bus_kwargs: dict[str, Any],
        initial_backoff_s: float,
        max_backoff_s: float,
        read_timeout_s: float,
        bounded_reader_size: int,
        stop_event: asyncio.Event,
        reconnect_event: asyncio.Event,
        on_state_change: Callable[[ConnectionState], Awaitable[None]],
        on_session_start: Callable[[can.BusABC], None],
        on_session_end: Callable[[], None],
        on_message_received: Callable[[can.Message], Awaitable[None]],
        on_should_reconnect: Callable[[], bool],
        on_idle_check: Callable[[], bool],
        on_reconnect_count: Callable[[], None],
    ) -> None:
        """Initialize connection manager.

        Args:
            logger: Logger for connection messages
            interface: CAN interface backend name
            channel: CAN channel identifier
            bus_kwargs: Additional python-can Bus constructor arguments
            initial_backoff_s: Initial reconnection delay
            max_backoff_s: Maximum reconnection delay
            read_timeout_s: Message read timeout
            bounded_reader_size: Size of bounded reader
            stop_event: Event signaling shutdown
            reconnect_event: Event signaling reconnection needed
            on_state_change: Callback for connection state changes
            on_session_start: Callback when session starts
            on_session_end: Callback when session ends
            on_message_received: Callback for received messages
            on_should_reconnect: Callback to check if reconnection needed
            on_idle_check: Callback for idle watchdog checks
            on_reconnect_count: Callback to increment reconnect counter
        """
        self.logger = logger
        self._interface = interface
        self._channel = channel
        self._bus_kwargs = bus_kwargs
        self._initial_backoff_s = initial_backoff_s
        self._max_backoff_s = max_backoff_s
        self._read_timeout_s = read_timeout_s
        self._bounded_reader_size = bounded_reader_size
        self._stop_event = stop_event
        self._reconnect_event = reconnect_event
        self._on_state_change = on_state_change
        self._on_session_start = on_session_start
        self._on_session_end = on_session_end
        self._on_message_received = on_message_received
        self._on_should_reconnect = on_should_reconnect
        self._on_idle_check = on_idle_check
        self._on_reconnect_count = on_reconnect_count

    async def run(self) -> None:  # pylint: disable=too-many-statements
        """Main connection loop: connect, run session, reconnect on failure.

        This method runs indefinitely until stop_event is set. It handles:
        - Establishing CAN bus connections
        - Running message receive sessions
        - Reconnecting on failures with exponential backoff
        - Clean shutdown on critical errors
        """
        attempt = 0
        had_rx = False

        while not self._stop_event.is_set():
            bus: can.BusABC | None = None
            try:
                # Transition to CONNECTING state
                await self._on_state_change(ConnectionState.CONNECTING)

                # Build connection parameters
                self.logger.info(
                    "Connecting to CAN (iface=%s, channel=%s)",
                    self._interface,
                    self._channel,
                )

                try:
                    bus = can.Bus(
                        interface=self._interface,
                        channel=self._channel,
                        **self._bus_kwargs,
                    )
                except can.CanError as e:
                    self.logger.warning("Connect failed: %s", e)
                    bus = None

                if bus is None:
                    self._on_reconnect_count()
                    await self._on_state_change(ConnectionState.DISCONNECTED)
                    if self._stop_event.is_set():
                        break
                    delay = self._calculate_backoff(attempt)
                    attempt += 1
                    self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
                    await asyncio.sleep(delay)
                    continue

                self.logger.info(
                    "Connected (iface=%s, channel=%s)", self._interface, self._channel
                )
                await self._on_state_change(ConnectionState.CONNECTED)

                had_rx = await self._run_session(bus)

            except asyncio.CancelledError:
                self.logger.info("Connection task cancelled; shutting down")
                break
            except PermissionError as e:
                self.logger.critical("Permission denied accessing CAN interface: %s", e)
                # Don't reconnect on permission errors
                break
            except can.CanError as e:
                self.logger.warning("CAN error (will retry): %s", e, exc_info=True)
                self._on_reconnect_count()
            except OSError as e:
                self.logger.error(
                    "OS error (network/device issue): %s", e, exc_info=True
                )
                self._on_reconnect_count()
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Last resort - log with full context for debugging
                self.logger.exception("Unexpected error in CAN bus loop: %s", e)
                self._on_reconnect_count()

            if self._stop_event.is_set():
                break

            # Transition to DISCONNECTED after session ends
            await self._on_state_change(ConnectionState.DISCONNECTED)

            # Compute backoff after a completed session
            self._on_reconnect_count()
            if had_rx:
                attempt = 0  # Reset backoff on successful RX
            delay = self._calculate_backoff(attempt)
            attempt += 1
            self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
            await asyncio.sleep(delay)

    async def _run_session(self, bus: can.BusABC) -> bool:
        """Run one connected session: setup, receive loop, teardown.

        Args:
            bus: Connected CAN bus instance

        Returns:
            True if any messages were received during the session
        """
        had_rx = False
        self._on_session_start(bus)

        loop = asyncio.get_running_loop()
        bounded = BoundedAsyncCanReader(
            loop=loop,
            maxsize=self._bounded_reader_size,
            drop_oldest=True,
        )
        notifier: can.Notifier | None = None

        try:
            notifier = can.Notifier(bus, [bounded.listener])

            while True:
                if self._on_should_reconnect():
                    self.logger.info("Reconnect requested; leaving reader loop")
                    break

                try:
                    msg = await asyncio.wait_for(bounded.get(), self._read_timeout_s)
                    had_rx = True
                except asyncio.TimeoutError:
                    # Heartbeat tick - check watchdogs
                    if self._on_idle_check():
                        continue
                    self.logger.debug(
                        "No CAN messages in the last %.1f seconds",
                        self._read_timeout_s,
                    )
                    continue

                # Pass message to handler
                await self._on_message_received(msg)

        finally:
            self._teardown_session(bus, notifier)
            self._on_session_end()

        return had_rx

    def _teardown_session(
        self, bus: can.BusABC | None, notifier: can.Notifier | None
    ) -> None:
        """Teardown CAN session by stopping notifier and shutting down bus.

        Args:
            bus: CAN bus to shutdown (can be None)
            notifier: CAN notifier to stop (can be None)
        """
        with suppress(Exception):
            if notifier is not None:
                notifier.stop()
        if bus is not None:
            with suppress(Exception):
                bus.shutdown()

    def _calculate_backoff(self, attempt: int) -> float:
        """Calculate exponential backoff delay with jitter.

        Args:
            attempt: Current attempt number (0-indexed)

        Returns:
            Delay in seconds (randomized between 0 and calculated backoff)
        """
        upper = min(
            self._max_backoff_s,
            self._initial_backoff_s * (2**attempt),
        )
        return random.uniform(0.0, upper)
