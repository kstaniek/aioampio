"""Ampio Bridge."""

import asyncio
from abc import ABC, abstractmethod
from contextlib import suppress
from dataclasses import dataclass
from enum import Enum, auto
import logging
import random
import time
from typing import Any, ClassVar
import uuid


import can

# Ensure built-in Ampio codec registers itself (no dynamic config needed)
from aioampio.codec import ampio as _ampio  # noqa: F401
from aioampio.config import AmpioConfig
from aioampio.controllers.alarm_control_panels import AlarmControlPanelsController
from aioampio.controllers.areas import AreasController
from aioampio.controllers.binary_sensors import BinarySensorsController
from aioampio.controllers.climates import ClimatesController
from aioampio.controllers.covers import CoversController
from aioampio.controllers.sensors import SensorsController
from aioampio.controllers.switches import SwitchesController
from aioampio.controllers.texts import TextsController
from aioampio.controllers.floors import FloorsController
from aioampio.controllers.valves import ValvesController

from .controllers.lights import LightsController
from .controllers.devices import DevicesController

from .codec.registry import registry
from .codec.base import CANFrame
from .state_store import StateStore
from .helpers.rx_reader import BoundedAsyncCanReader
from .util import CanInterface, _discover_backends


class ConnectionState(Enum):
    """Bridge connection state machine states."""

    DISCONNECTED = auto()  # Initial state, no bus connection
    CONNECTING = auto()  # Bus creation in progress
    CONNECTED = auto()  # Active session, receiving data
    RECONNECTING = auto()  # Triggered reconnect, teardown in progress
    STOPPING = auto()  # Shutdown requested
    STOPPED = auto()  # Final state, bridge stopped


class StateTransition:
    """Valid state transitions for the connection state machine."""

    # Define valid state transitions
    VALID_TRANSITIONS: dict[ConnectionState, set[ConnectionState]] = {
        ConnectionState.DISCONNECTED: {
            ConnectionState.CONNECTING,
            ConnectionState.STOPPING,
        },
        ConnectionState.CONNECTING: {
            ConnectionState.CONNECTED,
            ConnectionState.DISCONNECTED,
            ConnectionState.STOPPING,
        },
        ConnectionState.CONNECTED: {
            ConnectionState.RECONNECTING,
            ConnectionState.STOPPING,
        },
        ConnectionState.RECONNECTING: {
            ConnectionState.DISCONNECTED,
            ConnectionState.STOPPING,
        },
        ConnectionState.STOPPING: {
            ConnectionState.STOPPED,
        },
        ConnectionState.STOPPED: set(),  # Terminal state
    }

    @classmethod
    def is_valid(cls, from_state: ConnectionState, to_state: ConnectionState) -> bool:
        """Check if a state transition is valid.

        Args:
            from_state: Current state
            to_state: Target state

        Returns:
            True if transition is valid, False otherwise
        """
        return to_state in cls.VALID_TRANSITIONS.get(from_state, set())


@dataclass
class BridgeConfig:
    """Bridge configuration with validation.

    All timeouts are in seconds. Queue sizes are in number of messages.
    """

    # Connection timeouts
    read_timeout_s: float = 2.0
    reconnect_initial_s: float = 0.5
    reconnect_max_s: float = 30.0
    tx_timeout_s: float = 1.0

    # Watchdog timeouts (None to disable)
    idle_reconnect_s: float | None = 60.0
    rx_gap_reconnect_s: float | None = 10.0
    max_no_rx_after_connect_s: float | None = 10.0

    # Queue sizes
    rx_queue_size: int = 1000
    bounded_reader_size: int = 2000

    # Error thresholds
    tx_error_reconnect_threshold: int = 3
    max_consecutive_rx_errors: int = 10

    # Workers
    rx_worker_count: int = 1

    # Metrics
    rate_smoothing_alpha: float = 0.6  # EMA factor (0..1), higher = more reactive
    queue_full_log_interval: int = 100  # Log every N drops

    # Constants
    CTRL_CAN_ID: ClassVar[int] = 0x0F000000

    def __post_init__(self) -> None:  # pylint: disable=too-many-branches
        """Validate configuration relationships."""
        errors = []

        # Validate timeouts are positive
        if self.read_timeout_s <= 0:
            errors.append(f"read_timeout_s must be > 0, got {self.read_timeout_s}")

        if self.reconnect_initial_s <= 0:
            errors.append(
                f"reconnect_initial_s must be > 0, got {self.reconnect_initial_s}"
            )

        if self.reconnect_max_s <= 0:
            errors.append(f"reconnect_max_s must be > 0, got {self.reconnect_max_s}")

        if self.tx_timeout_s <= 0:
            errors.append(f"tx_timeout_s must be > 0, got {self.tx_timeout_s}")

        # Validate reconnect relationship
        if self.reconnect_initial_s > self.reconnect_max_s:
            errors.append(
                f"reconnect_initial_s ({self.reconnect_initial_s}) must be <= "
                f"reconnect_max_s ({self.reconnect_max_s})"
            )

        # Validate watchdog timeout relationships
        if self.max_no_rx_after_connect_s and self.idle_reconnect_s:
            if self.max_no_rx_after_connect_s > self.idle_reconnect_s:
                errors.append(
                    f"max_no_rx_after_connect_s ({self.max_no_rx_after_connect_s}) "
                    f"should be <= idle_reconnect_s ({self.idle_reconnect_s})"
                )

        if self.rx_gap_reconnect_s and self.idle_reconnect_s:
            if self.rx_gap_reconnect_s > self.idle_reconnect_s:
                errors.append(
                    f"rx_gap_reconnect_s ({self.rx_gap_reconnect_s}) should be <= "
                    f"idle_reconnect_s ({self.idle_reconnect_s})"
                )

        # Validate queue sizes
        if self.rx_queue_size <= 0:
            errors.append(f"rx_queue_size must be > 0, got {self.rx_queue_size}")

        if self.bounded_reader_size <= 0:
            errors.append(
                f"bounded_reader_size must be > 0, got {self.bounded_reader_size}"
            )

        # Validate thresholds
        if self.tx_error_reconnect_threshold <= 0:
            errors.append(
                f"tx_error_reconnect_threshold must be > 0, "
                f"got {self.tx_error_reconnect_threshold}"
            )

        if self.max_consecutive_rx_errors <= 0:
            errors.append(
                f"max_consecutive_rx_errors must be > 0, "
                f"got {self.max_consecutive_rx_errors}"
            )

        # Validate worker count
        if self.rx_worker_count <= 0:
            errors.append(f"rx_worker_count must be > 0, got {self.rx_worker_count}")

        # Validate rate smoothing alpha
        if not 0.0 < self.rate_smoothing_alpha <= 1.0:
            errors.append(
                f"rate_smoothing_alpha must be in (0, 1], "
                f"got {self.rate_smoothing_alpha}"
            )

        # Validate log interval
        if self.queue_full_log_interval <= 0:
            errors.append(
                f"queue_full_log_interval must be > 0, "
                f"got {self.queue_full_log_interval}"
            )

        if errors:
            raise ValueError(
                "Bridge configuration validation failed:\n  - " + "\n  - ".join(errors)
            )


class Watchdog(ABC):
    """Base class for watchdog timers that detect connection issues.

    Watchdogs monitor various aspects of the connection and signal when
    a reconnect should be triggered.
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
        base = last_rx or connected_since or now
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


class AmpioBridge:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Ampio Bridge main class."""

    # --- Lifecycle: __init__, initialize(), start(), stop() -----------------

    def __init__(  # pylint: disable=too-many-statements
        self,
        cfg: dict[str, Any],
        interface: CanInterface,
        channel: str,
        bridge_config: BridgeConfig | None = None,
        **bus_kwargs: Any,
    ) -> None:
        """Initialize the Ampio Bridge.

        Args:
            cfg: Ampio configuration dictionary
            interface: CAN interface backend name (e.g., 'socketcan', 'kvaser')
            channel: CAN channel identifier (interface-specific, e.g., 'can0', 'vcan0')
            bridge_config: Bridge configuration. If None, uses defaults
            bus_kwargs: Additional arguments passed to python-can Bus constructor
        """
        self._ampio_cfg = cfg
        self._interface: str = self._validate_interface(interface)
        self._channel: str = channel
        self._bus_kwargs: dict[str, Any] = dict(bus_kwargs or {})
        self._bridge_config = bridge_config or BridgeConfig()

        self.logger = logging.getLogger(f"{__package__}[{self._channel}]")

        self._config = AmpioConfig(self)

        self.state_store = StateStore(self)

        self._devices = DevicesController(self)
        self._lights = LightsController(self)
        self._alarm_control_panels = AlarmControlPanelsController(self)
        self._texts = TextsController(self)
        self._binary_sensors = BinarySensorsController(self)
        self._sensor = SensorsController(self)
        self._floors = FloorsController(self)
        self._areas = AreasController(self)
        self._switches = SwitchesController(self)
        self._covers = CoversController(self)
        self._valves = ValvesController(self)
        self._climates = ClimatesController(self)

        self._whitelist: set[int] = set()

        # State machine
        self._connection_state = ConnectionState.DISCONNECTED
        self._state_lock = asyncio.Lock()
        self._session_id: str | None = None

        self._transport: asyncio.Task[None] | None = None
        self._bus: can.BusABC | None = None
        self._bus_lock = asyncio.Lock()  # Protect bus access from race conditions
        self._stop_event: asyncio.Event = asyncio.Event()

        self._proc_queue: asyncio.Queue[can.Message] = asyncio.Queue(
            maxsize=self._bridge_config.rx_queue_size
        )
        self._rx_workers: list[asyncio.Task] = []

        self._reconnect_now: asyncio.Event = asyncio.Event()
        self._connected_since_mono: float | None = None
        self._connected_evt = asyncio.Event()

        # Watchdog manager
        self._watchdog_manager = WatchdogManager()
        self._setup_watchdogs()

        # metrics
        self._rx_total = 0
        self._rx_enqueued = 0  # into bounded reader
        self._rx_backpressure_drop = 0
        self._rx_proc_queued = 0  # into processing queue
        self._tx_errors = 0
        self._tx_total = 0
        self._reconnects = 0
        self._last_rx_mono: float | None = None
        self._last_tx_mono: float | None = None
        self._tx_error_streak = 0

        # rate tracking / smoothing
        self._rate_prev_time = time.monotonic()
        self._rate_prev_rx = 0
        self._rate_prev_tx = 0
        self._rx_per_s = 0.0
        self._tx_per_s = 0.0

        # Queue full logging (prevent log spam)
        self._rx_backpressure_drop_logged = 0

    def _setup_watchdogs(self) -> None:
        """Set up watchdog timers based on configuration."""
        cfg = self._bridge_config

        # Add notifier stall watchdog if configured
        if cfg.max_no_rx_after_connect_s is not None:
            self._watchdog_manager.add_watchdog(
                NotifierStallWatchdog(
                    self.logger,
                    self._reconnect_now,
                    cfg.max_no_rx_after_connect_s,
                )
            )

        # Add RX gap watchdog if configured
        if cfg.rx_gap_reconnect_s is not None:
            self._watchdog_manager.add_watchdog(
                RxGapWatchdog(
                    self.logger,
                    self._reconnect_now,
                    cfg.rx_gap_reconnect_s,
                )
            )

        # Add idle watchdog if configured
        if cfg.idle_reconnect_s is not None:
            self._watchdog_manager.add_watchdog(
                IdleWatchdog(
                    self.logger,
                    self._reconnect_now,
                    cfg.idle_reconnect_s,
                )
            )

    async def initialize(self) -> None:
        """Initialize the bridge."""
        await self._config.initialize(self._ampio_cfg)
        self._whitelist = self._config.whitelist_can_ids

        await asyncio.gather(
            self._floors.initialize(),
            self._areas.initialize(),
            self._devices.initialize(),
            self._lights.initialize(),
            self._alarm_control_panels.initialize(),
            self._texts.initialize(),
            self._binary_sensors.initialize(),
            self._sensor.initialize(),
            self._switches.initialize(),
            self._covers.initialize(),
            self._valves.initialize(),
            self._climates.initialize(),
        )

    async def start(self) -> None:
        """Start the bridge."""
        if self._transport and not self._transport.done():
            self.logger.debug("Bridge already running")
            return
        self._stop_event.clear()
        await self._transition_state(ConnectionState.CONNECTING)
        self._transport = asyncio.create_task(self._run())
        self.logger.info("Bridge started")

    async def stop(self) -> None:
        """Stop the bridge."""
        await self._transition_state(ConnectionState.STOPPING)
        self._stop_event.set()
        if self._transport is None:
            await self._transition_state(ConnectionState.STOPPED)
            return
        self._transport.cancel()
        with suppress(asyncio.CancelledError):
            await self._transport
        self._transport = None
        if self._bus is not None:
            with suppress(Exception):
                self._bus.shutdown()
            self._bus = None
        await self._transition_state(ConnectionState.STOPPED)
        self.logger.info("Bridge stopped")

    # --- State Machine Methods ----------------------------------------------

    async def _transition_state(self, new_state: ConnectionState) -> None:
        """Thread-safe state transition with logging and validation.

        Args:
            new_state: Target state to transition to

        Raises:
            ValueError: If transition is not valid
        """
        async with self._state_lock:
            old_state = self._connection_state

            # Validate transition
            if not StateTransition.is_valid(old_state, new_state):
                self.logger.error(
                    "Invalid state transition: %s -> %s",
                    old_state.name,
                    new_state.name,
                )
                raise ValueError(
                    f"Invalid state transition: {old_state.name} -> {new_state.name}"
                )

            self._connection_state = new_state
            self.logger.debug(
                "State transition: %s -> %s", old_state.name, new_state.name
            )

    @property
    def connection_state(self) -> ConnectionState:
        """Return current connection state."""
        return self._connection_state

    # --- Public API: control & status --------------------------------------

    async def wait_connected(self, timeout: float | None = None) -> bool:
        """Wait until the bridge is connected (or timeout)."""
        try:
            await asyncio.wait_for(self._connected_evt.wait(), timeout)
            return True
        except asyncio.TimeoutError:
            return False

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._connection_state == ConnectionState.CONNECTED

    @property
    def reconnecting(self) -> bool:
        """Return True if a reconnect is pending/ongoing."""
        return self._connection_state in (
            ConnectionState.RECONNECTING,
            ConnectionState.CONNECTING,
        )

    def trigger_reconnect(self, reason: str = "manual") -> None:
        """Trigger a reconnect as soon as possible."""
        if not self._reconnect_now.is_set():
            self.logger.info("Reconnect requested (%s)", reason)
            self._reconnect_now.set()

    async def send(self, can_id: int, data: bytes | memoryview) -> None:
        """Send a CAN frame (non-blocking for the event loop).

        Args:
            can_id: CAN arbitration ID (29-bit extended)
            data: Frame payload (max 8 bytes for CAN 2.0)

        Note:
            Messages are dropped silently if bus is not connected or reconnecting.
            Errors are logged and counted in metrics.
        """
        # Fast path: early exit without lock if reconnecting
        if self._reconnect_now.is_set():
            self.logger.debug("TX dropped; reconnect pending")
            return

        # Lock-protected bus access to prevent TOCTOU race condition
        async with self._bus_lock:
            bus = self._bus
            if bus is None:
                self.logger.debug("TX dropped; bus not connected")
                return

            msg = can.Message(
                arbitration_id=can_id,
                data=bytes(data),
                is_extended_id=True,
                is_fd=False,
            )
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(
                    None, bus.send, msg, self._bridge_config.tx_timeout_s
                )
                self._tx_total += 1
                self._last_tx_mono = time.monotonic()
                self._tx_error_streak = 0  # Reset on success
                self.logger.debug("TX id=0x%X len=%d", can_id, len(msg.data))
            except can.CanError as e:
                self._handle_tx_error(can_id, e)
            except OSError as e:
                # Network/device errors (e.g., device unplugged)
                self._handle_tx_error(can_id, e)

    def _handle_tx_error(self, can_id: int, error: Exception) -> None:
        """Handle transmission errors with reconnect logic.

        Args:
            can_id: The CAN ID that failed to send
            error: The exception that occurred
        """
        self._tx_errors += 1
        self._tx_error_streak += 1
        self.logger.error("TX failed; dropping frame id=0x%X: %s", can_id, error)

        if (
            "closed" in str(error).lower()
            or self._tx_error_streak >= self._bridge_config.tx_error_reconnect_threshold
        ):
            self.logger.warning(
                "TX error threshold reached (%d consecutive failures); triggering reconnect",
                self._tx_error_streak,
            )
            self._reconnect_now.set()

    # --- Public API: metrics & info ----------------------------------------

    @property
    def connection_uptime_s(self) -> float | None:
        """Return connection uptime in seconds, or None if not connected."""
        if self._connected_since_mono is None:
            return None
        return max(0.0, time.monotonic() - self._connected_since_mono)

    @property
    def metrics(self) -> dict[str, Any]:
        """Return connection and message metrics."""
        self._update_rates()
        now = time.monotonic()
        return {
            "connected": self.connected,
            "connection_state": self._connection_state.name,
            "session_id": self._session_id,
            "reconnects": self._reconnects,
            "rx_total": self._rx_total,
            "tx_total": self._tx_total,
            "rx_rate_s": self._rx_per_s,
            "tx_rate_s": self._tx_per_s,
            "rx_enqueued": self._rx_enqueued,
            "rx_proc_queued": self._rx_proc_queued,
            "rx_dropped": self._rx_backpressure_drop,
            "tx_errors": self._tx_errors,
            "rx_queue_depth": self._proc_queue.qsize(),
            "last_rx_age_s": (
                None
                if self._last_rx_mono is None
                else max(0.0, now - self._last_rx_mono)
            ),
            "last_tx_age_s": (
                None
                if self._last_tx_mono is None
                else max(0.0, now - self._last_tx_mono)
            ),
            "connection_uptime_s": self.connection_uptime_s,
        }

    def _update_rates(self) -> None:
        """Update smoothed RX/TX per-second rates (EMA)."""
        now = time.monotonic()
        dt = max(1e-3, now - self._rate_prev_time)
        drx = self._rx_total - self._rate_prev_rx
        dtx = self._tx_total - self._rate_prev_tx

        inst_rx = drx / dt
        inst_tx = dtx / dt
        a = self._bridge_config.rate_smoothing_alpha

        # Exponential moving average
        self._rx_per_s = a * inst_rx + (1.0 - a) * self._rx_per_s
        self._tx_per_s = a * inst_tx + (1.0 - a) * self._tx_per_s

        self._rate_prev_time = now
        self._rate_prev_rx = self._rx_total
        self._rate_prev_tx = self._tx_total

    # --- Public API: subcontrollers & config --------------------------------

    @property
    def floors(self) -> FloorsController:
        """Return the floors controller."""
        return self._floors

    @property
    def areas(self) -> AreasController:
        """Return the areas controller."""
        return self._areas

    @property
    def devices(self) -> DevicesController:
        """Return the devices managed by the bridge."""
        return self._devices

    @property
    def lights(self) -> LightsController:
        """Return the lights controller."""
        return self._lights

    @property
    def alarm_control_panels(self) -> AlarmControlPanelsController:
        """Return the alarm control panels controller."""
        return self._alarm_control_panels

    @property
    def texts(self) -> TextsController:
        """Return the texts controller."""
        return self._texts

    @property
    def binary_sensors(self) -> BinarySensorsController:
        """Return the binary sensors controller."""
        return self._binary_sensors

    @property
    def sensors(self) -> SensorsController:
        """Return the sensors controller."""
        return self._sensor

    @property
    def switches(self) -> SwitchesController:
        """Return the switches controller."""
        return self._switches

    @property
    def covers(self) -> CoversController:
        """Return the covers controller."""
        return self._covers

    @property
    def valves(self) -> ValvesController:
        """Return the valves controller."""
        return self._valves

    @property
    def climates(self) -> ClimatesController:
        """Return the climates controller."""
        return self._climates

    @property
    def config(self) -> AmpioConfig:
        """Return the current configuration."""
        return self._config

    # --- Internal main loop -------------------------------------------------

    async def _run(self) -> None:  # pylint: disable=too-many-statements,too-many-branches
        """Main bridge loop: connect, run session, reconnect on failure."""
        attempt = 0
        had_rx = False
        while not self._stop_event.is_set():
            bus: can.BusABC | None = None
            try:
                # Transition to CONNECTING state
                if self._connection_state == ConnectionState.DISCONNECTED:
                    await self._transition_state(ConnectionState.CONNECTING)

                # Build connection parameters each attempt (in case they change)
                interface, channel, kwargs = (
                    self._interface,
                    self._channel,
                    self._bus_kwargs,
                )
                self.logger.info(
                    "Connecting to CAN (iface=%s, channel=%s)", interface, channel
                )

                try:
                    bus = can.Bus(
                        interface=interface,
                        channel=channel,
                        **kwargs,
                    )
                except can.CanError as e:
                    self.logger.warning("Connect failed: %s", e)
                    bus = None

                if bus is None:
                    self._reconnects += 1
                    await self._transition_state(ConnectionState.DISCONNECTED)
                    if self._stop_event.is_set():
                        break
                    delay = self._next_backoff(attempt)
                    attempt += 1
                    self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
                    await asyncio.sleep(delay)
                    continue

                self.logger.info("Connected (iface=%s, channel=%s)", interface, channel)
                await self._transition_state(ConnectionState.CONNECTED)

                had_rx = await self._run_session(bus)

            except asyncio.CancelledError:
                self.logger.info("Bridge task cancelled; shutting down")
                break
            except PermissionError as e:
                self.logger.critical("Permission denied accessing CAN interface: %s", e)
                # Don't reconnect on permission errors
                break
            except can.CanError as e:
                self.logger.warning("CAN error (will retry): %s", e, exc_info=True)
                self._reconnects += 1
            except OSError as e:
                self.logger.error(
                    "OS error (network/device issue): %s", e, exc_info=True
                )
                self._reconnects += 1
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Last resort - log with full context for debugging
                self.logger.exception("Unexpected error in CAN bus loop: %s", e)
                self._reconnects += 1
            finally:
                # session teardown was handled inside _run_session; nothing else here
                pass

            if self._stop_event.is_set():
                break

            # Transition to DISCONNECTED after session ends
            await self._transition_state(ConnectionState.DISCONNECTED)

            # Compute backoff after a completed session
            self._reconnects += 1
            if had_rx:
                attempt = 0
            delay = self._next_backoff(attempt)
            attempt += 1
            self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
            await asyncio.sleep(delay)

    async def _run_session(self, bus: can.BusABC) -> bool:
        """Run one connected session: setup, receive loop, teardown."""
        had_rx = False
        self._bus = bus
        self._reset_connect_state()
        self._apply_filters()

        loop = asyncio.get_running_loop()
        bounded = BoundedAsyncCanReader(
            loop=loop,
            maxsize=self._bridge_config.bounded_reader_size,
            drop_oldest=True,
            on_drop=self._inc_drop,
            on_enqueue=self._inc_enq,
        )
        notifier: can.Notifier | None = None
        try:
            notifier = can.Notifier(bus, [bounded.listener])
            self._start_rx_workers(n=self._bridge_config.rx_worker_count)
            while True:
                if self._should_reconnect():
                    self.logger.info("Reconnect requested; leaving reader loop")
                    break

                try:
                    msg = await asyncio.wait_for(
                        bounded.get(), self._bridge_config.read_timeout_s
                    )
                    had_rx = True
                except asyncio.TimeoutError:
                    # heartbeat tick
                    if self._idle_watchdog():
                        continue
                    self.logger.debug(
                        "No CAN messages in the last %.1f seconds",
                        self._bridge_config.read_timeout_s,
                    )
                    continue

                try:
                    self._proc_queue.put_nowait(msg)
                    self._rx_proc_queued += 1
                except asyncio.QueueFull:
                    self._rx_backpressure_drop += 1
                    # Log periodically to avoid log spam
                    drops_since_log = (
                        self._rx_backpressure_drop - self._rx_backpressure_drop_logged
                    )
                    if drops_since_log >= self._bridge_config.queue_full_log_interval:
                        self.logger.warning(
                            "RX queue full; dropped %d messages (total: %d, queue depth: %d/1000)",
                            drops_since_log,
                            self._rx_backpressure_drop,
                            self._proc_queue.qsize(),
                        )
                        self._rx_backpressure_drop_logged = self._rx_backpressure_drop
        finally:
            self._teardown_session(bus, notifier)
            await self._stop_rx_workers()
            self._bus = None
            self._clear_connect_state()

            # drain processing queue to avoid stale backlog across sessions
            while not self._proc_queue.empty():
                with suppress(asyncio.QueueEmpty):
                    self._proc_queue.get_nowait()
        return had_rx

    # --- Internal RX path ---------------------------------------------------

    def _start_rx_workers(self, n: int = 1) -> None:
        async def worker(idx: int) -> None:
            self.logger.debug("RX worker %d started", idx)
            consecutive_errors = 0
            max_consecutive_errors = 10

            while not self._stop_event.is_set():
                try:
                    msg = await self._proc_queue.get()
                except asyncio.CancelledError:
                    self.logger.debug("RX worker %d cancelled", idx)
                    break

                try:
                    self._rx_total += 1
                    self._last_rx_mono = time.monotonic()
                    await self._on_frame(msg)
                    consecutive_errors = 0  # Reset on success
                except Exception as e:  # pylint: disable=broad-exception-caught
                    # Re-raise cancellation to properly shutdown
                    if isinstance(e, asyncio.CancelledError):
                        raise
                    consecutive_errors += 1
                    self.logger.exception(
                        "RX worker %d processing failed (%d consecutive): %s",
                        idx,
                        consecutive_errors,
                        e,
                    )

                    if consecutive_errors >= max_consecutive_errors:
                        self.logger.critical(
                            "RX worker %d: too many consecutive errors (%d); stopping worker",
                            idx,
                            consecutive_errors,
                        )
                        break

            self.logger.debug("RX worker %d stopped", idx)

        self._rx_workers = [asyncio.create_task(worker(i)) for i in range(n)]
        self.logger.info("Started %d RX worker(s)", n)

    async def _stop_rx_workers(self) -> None:
        for t in self._rx_workers:
            t.cancel()
        for t in self._rx_workers:
            with suppress(asyncio.CancelledError):
                await t
        self._rx_workers.clear()

    async def _on_frame(self, msg: can.Message) -> None:  # pylint: disable=too-many-return-statements
        """Handle incoming CAN frame."""
        if not msg.is_extended_id:
            self.logger.debug("Ignoring non-extended CAN frame: %s", msg)
            return
        if msg.is_remote_frame:
            self.logger.debug("Ignoring remote CAN frame: %s", msg)
            return
        if msg.dlc != len(msg.data):
            self.logger.warning("Ignoring CAN frame with invalid DLC: %s", msg)
            return
        if not msg.data:
            self.logger.debug("Ignoring empty CAN frame: %s", msg)
            return
        frame = CANFrame(can_id=msg.arbitration_id, data=memoryview(msg.data))
        try:
            msgs = registry().decode(frame)
        except ValueError as e:
            # Invalid frame data format
            self.logger.warning("Invalid frame data id=0x%X: %s", msg.arbitration_id, e)
            return
        except KeyError as e:
            # No decoder registered for this frame type
            self.logger.debug("No decoder for frame id=0x%X: %s", msg.arbitration_id, e)
            return
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Unexpected decoder error - log with full context
            self.logger.exception(
                "Decoder failed for frame id=0x%X: %s", msg.arbitration_id, e
            )
            return
        if not msgs:
            return
        for m in msgs:
            await self.state_store.apply_message(m)

    # --- Internal connection/watchdog helpers -------------------------------

    def _apply_filters(self) -> None:
        """Apply CAN ID whitelist as hardware/driver filters."""
        if not self._whitelist or self._bus is None:
            return
        # Exact match for extended (29-bit) IDs
        filters = [
            {"can_id": can_id, "can_mask": 0x1FFFFFFF, "extended": True}
            for can_id in self._whitelist
        ]
        try:
            self._bus.set_filters(filters)  # type: ignore[arg-type]
            self.logger.info("Device whitelist applied for %d devices", len(filters))
        except Exception:  # pylint: disable=broad-exception-caught
            # Some drivers may not support filters; don’t crash the bridge
            self.logger.warning(
                "Bus driver does not support set_filters()", exc_info=True
            )

    def _should_reconnect(self) -> bool:
        """Return True if we should reconnect."""
        return self._stop_event.is_set() or self._reconnect_now.is_set()

    def _idle_watchdog(self) -> bool:
        """Check all watchdogs and return True if any triggered.

        Returns:
            True if any watchdog triggered a reconnect
        """
        if not self._watchdog_manager.is_enabled():
            return False

        now = time.monotonic()
        return self._watchdog_manager.check_all(
            now,
            self._connected_since_mono,
            self._last_rx_mono,
        )

    def _reset_connect_state(self) -> None:
        """Reset connection state on connect."""
        self._session_id = str(uuid.uuid4())[:8]
        self._connected_evt.set()
        self._reconnect_now.clear()
        self._connected_since_mono = time.monotonic()
        self.logger.info("Session started: %s", self._session_id)

    def _clear_connect_state(self) -> None:
        """Clear connection state on disconnect."""
        if self._session_id:
            uptime = self.connection_uptime_s or 0.0
            self.logger.info(
                "Session ended: %s (uptime: %.1fs, rx: %d, tx: %d)",
                self._session_id,
                uptime,
                self._rx_total,
                self._tx_total,
            )
        self._connected_evt.clear()
        self._connected_since_mono = None
        self._session_id = None

    def _teardown_session(
        self, bus: can.BusABC | None, notifier: can.Notifier | None
    ) -> None:
        """Teardown CAN session.

        Stop the notifier thread first, then shut down the bus.
        Workers are awaited by the caller after leaving the thread context.
        """
        with suppress(Exception):
            if notifier is not None:
                notifier.stop()
        if bus is not None:
            with suppress(Exception):
                bus.shutdown()

    def _next_backoff(self, attempt: int) -> float:
        """Calculate the next backoff delay."""
        upper = min(
            self._bridge_config.reconnect_max_s,
            self._bridge_config.reconnect_initial_s * (2**attempt),
        )
        return random.uniform(0.0, upper)

    # --- Internal counters/queue helpers ------------------------------------

    def _inc_drop(self) -> None:
        self._rx_backpressure_drop += 1

    def _inc_enq(self) -> None:
        self._rx_enqueued += 1

    def _validate_interface(self, interface: str) -> str:
        """Normalize and validate the requested python-can interface early."""
        name = (interface or "").strip().lower()
        if not name:
            raise ValueError("CAN interface must be a non-empty string")

        available = _discover_backends()
        # 'waveshare' is your custom backend; it's included in available via fallback.
        if name not in available:
            pretty = ", ".join(sorted(available)) or "unknown (python-can not detected)"
            raise ValueError(
                f"Unknown CAN interface '{interface}'. "
                f"Detected/known backends: {pretty}."
            )
        return name
