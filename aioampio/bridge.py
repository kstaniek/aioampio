"""Ampio Bridge."""

import asyncio
from contextlib import suppress
import logging
import random
import time
from typing import Any
import uuid


import can

# Ensure built-in Ampio codec registers itself (no dynamic config needed)
from aioampio.codec import ampio as _ampio  # noqa: F401
from aioampio.config import AmpioConfig
from aioampio.bridge_config import BridgeConfig
from aioampio.metrics import BridgeMetrics, BridgeMetricsDict
from aioampio.rx_workers import RxWorkerManager
from aioampio.state_machine import ConnectionState, StateTransition
from aioampio.tx_handler import TxHandler
from aioampio.watchdog import (
    IdleWatchdog,
    NotifierStallWatchdog,
    RxGapWatchdog,
    WatchdogManager,
)
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

        self.logger = logging.getLogger(f"{__package__}.{self._channel}")

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
        self._bus_lock = asyncio.Lock()
        self._lifecycle_lock = asyncio.Lock()
        self._reconnect_now = asyncio.Event()
        self._stop_event: asyncio.Event = asyncio.Event()

        self._proc_queue: asyncio.Queue[can.Message] = asyncio.Queue(
            maxsize=self._bridge_config.rx_queue_size
        )

        # TX handler for message transmission
        self._tx_handler = TxHandler(
            logger=self.logger,
            bus_lock=self._bus_lock,
            reconnect_event=self._reconnect_now,
            tx_timeout_s=self._bridge_config.tx_timeout_s,
            tx_error_threshold=self._bridge_config.tx_error_reconnect_threshold,
            get_bus=lambda: self._bus,
            on_tx_success=self._on_tx_success,
            on_tx_error=self._on_tx_error,
        )

        # RX worker manager for message processing
        self._rx_worker_manager: RxWorkerManager | None = None

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
        """Start a new connection lifecycle, unless one is already running."""
        async with self._lifecycle_lock:
            if self._transport and not self._transport.done():
                return
            self._stop_event.clear()
            self._reconnect_now.clear()
            await self._transition_state(ConnectionState.CONNECTING)
            self._transport = asyncio.create_task(self._run())
            self.logger.info("Bridge started")

    async def stop(self) -> None:
        """Stop once and finish resource cleanup even if the caller is cancelled."""
        async with self._lifecycle_lock:
            if self._connection_state == ConnectionState.STOPPED:
                return
            task = asyncio.create_task(self._stop_transport())
            try:
                await asyncio.shield(task)
            except asyncio.CancelledError:
                await task
                raise

    async def _stop_transport(self) -> None:
        """Cancel the connection task and release all session resources."""
        await self._transition_state(ConnectionState.STOPPING)
        self._stop_event.set()
        self._reconnect_now.set()
        try:
            if self._transport is not None:
                self._transport.cancel()
                with suppress(asyncio.CancelledError):
                    await self._transport
        except Exception:  # pylint: disable=broad-exception-caught
            self.logger.exception("Bridge transport failed during shutdown")
        finally:
            await self._stop_rx_workers()
            if self._bus is not None:
                await self._teardown_session(self._bus, None)
            self._clear_connect_state()
            self._transport = None
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
        # Delegate to TX handler
        await self._tx_handler.send(can_id, data)

    def _on_tx_success(self) -> None:
        """Callback for successful transmission (updates metrics)."""
        self._tx_total += 1
        self._last_tx_mono = time.monotonic()

    def _on_tx_error(self, error: Exception) -> None:
        """Callback for transmission error (updates metrics).

        Args:
            error: The exception that occurred
        """
        self._tx_errors += 1

    # --- Public API: metrics & info ----------------------------------------

    @property
    def connection_uptime_s(self) -> float | None:
        """Return connection uptime in seconds, or None if not connected."""
        if self._connected_since_mono is None:
            return None
        return max(0.0, time.monotonic() - self._connected_since_mono)

    @property
    def metrics(self) -> BridgeMetrics:
        """Return connection and message metrics.

        Returns:
            Structured metrics with health assessment capabilities
        """
        self._update_rates()
        now = time.monotonic()
        return BridgeMetrics(
            connected=self.connected,
            connection_state=self._connection_state.name,
            session_id=self._session_id,
            reconnects=self._reconnects,
            connection_uptime_s=self.connection_uptime_s,
            rx_total=self._rx_total,
            tx_total=self._tx_total,
            rx_enqueued=self._rx_enqueued,
            rx_proc_queued=self._rx_proc_queued,
            rx_dropped=self._rx_backpressure_drop,
            tx_errors=self._tx_errors,
            rx_rate_s=self._rx_per_s,
            tx_rate_s=self._tx_per_s,
            rx_queue_depth=self._proc_queue.qsize(),
            last_rx_age_s=(
                None
                if self._last_rx_mono is None
                else max(0.0, now - self._last_rx_mono)
            ),
            last_tx_age_s=(
                None
                if self._last_tx_mono is None
                else max(0.0, now - self._last_tx_mono)
            ),
        )

    def get_metrics_dict(self) -> BridgeMetricsDict:
        """Return metrics as dictionary (backward compatibility).

        Returns:
            Dictionary with all metrics
        """
        return self.metrics.to_dict()

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

    async def _run(self) -> None:
        """Connect, run a session, and retry recoverable failures."""
        attempt = 0
        try:
            while not self._stop_event.is_set():
                had_rx = False
                try:
                    if self._connection_state == ConnectionState.DISCONNECTED:
                        await self._transition_state(ConnectionState.CONNECTING)
                    self.logger.info(
                        "Connecting to CAN (iface=%s, channel=%s)",
                        self._interface,
                        self._channel,
                    )
                    bus = await self._create_bus(
                        self._interface, self._channel, self._bus_kwargs
                    )
                    had_rx = await self._run_session(bus)
                except PermissionError:
                    self.logger.exception("Permission denied accessing CAN interface")
                    break
                except (can.CanError, OSError):
                    self.logger.warning(
                        "CAN connection failed; retrying", exc_info=True
                    )
                except Exception:  # pylint: disable=broad-exception-caught
                    self.logger.exception("Unexpected error in CAN bus loop")

                if self._stop_event.is_set():
                    break
                await self._transition_state(ConnectionState.DISCONNECTED)
                self._reconnects += 1
                if had_rx:
                    attempt = 0
                delay = self._next_backoff(attempt)
                attempt += 1
                self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
                await asyncio.sleep(delay)
        except asyncio.CancelledError:
            self.logger.info("Bridge task cancelled; shutting down")
        finally:
            self._connected_evt.clear()
            if (
                not self._stop_event.is_set()
                and self._connection_state != ConnectionState.DISCONNECTED
            ):
                if self._connection_state == ConnectionState.CONNECTED:
                    await self._transition_state(ConnectionState.RECONNECTING)
                await self._transition_state(ConnectionState.DISCONNECTED)

    async def _create_bus(
        self, interface: str, channel: str, kwargs: dict[str, Any]
    ) -> can.BusABC:
        """Create the bus off-loop and close a late connection after cancellation."""
        task = asyncio.create_task(
            asyncio.to_thread(can.Bus, interface=interface, channel=channel, **kwargs)
        )
        try:
            return await asyncio.shield(task)
        except asyncio.CancelledError:
            # The worker cannot be cancelled; wait for it to release its resources.
            with suppress(Exception):
                bus = await task
                await asyncio.to_thread(bus.shutdown)
            raise

    async def _run_session(self, bus: can.BusABC) -> bool:
        """Run one connected session: setup, receive loop, teardown."""
        had_rx = False
        notifier: can.Notifier | None = None
        try:
            async with self._bus_lock:
                self._bus = bus
                self._apply_filters()
                bounded = BoundedAsyncCanReader(
                    loop=asyncio.get_running_loop(),
                    maxsize=self._bridge_config.bounded_reader_size,
                    drop_oldest=True,
                    on_drop=self._inc_drop,
                    on_enqueue=self._inc_enq,
                )
                notifier = can.Notifier(bus, [bounded.listener])
                self._start_rx_workers(n=self._bridge_config.rx_worker_count)
                await self._transition_state(ConnectionState.CONNECTED)
                self._tx_handler.reset_error_streak()
                self._reset_connect_state()
                self.logger.info(
                    "Connected (iface=%s, channel=%s)", self._interface, self._channel
                )
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
            self._connected_evt.clear()
            self._reconnect_now.set()
            if self._connection_state == ConnectionState.CONNECTED:
                await self._transition_state(ConnectionState.RECONNECTING)
            try:
                await self._stop_rx_workers()
            finally:
                await self._teardown_session(bus, notifier)
                self._clear_connect_state()
                while not self._proc_queue.empty():
                    with suppress(asyncio.QueueEmpty):
                        self._proc_queue.get_nowait()
        return had_rx

    # --- Internal RX path ---------------------------------------------------

    def _start_rx_workers(self, n: int = 1) -> None:
        """Start RX worker pool using RxWorkerManager."""
        self._rx_worker_manager = RxWorkerManager(
            logger=self.logger,
            proc_queue=self._proc_queue,
            stop_event=self._stop_event,
            on_frame=self._on_frame,
            on_message_processed=self._on_rx_message_processed,
            max_consecutive_errors=self._bridge_config.max_consecutive_rx_errors,
            on_worker_failed=lambda: self.trigger_reconnect("RX worker failed"),
        )
        self._rx_worker_manager.start(n)

    async def _stop_rx_workers(self) -> None:
        """Stop RX worker pool."""
        if self._rx_worker_manager:
            await self._rx_worker_manager.stop()
            self._rx_worker_manager = None

    def _on_rx_message_processed(self) -> None:
        """Callback when RX message is processed (updates metrics)."""
        self._rx_total += 1
        self._last_rx_mono = time.monotonic()

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
        self._last_rx_mono = None
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

    async def _teardown_session(
        self, bus: can.BusABC | None, notifier: can.Notifier | None
    ) -> None:
        """Wait for sends, detach the bus, and close blocking resources off-loop."""

        def shutdown() -> None:
            with suppress(Exception):
                if notifier is not None:
                    notifier.stop()
            if bus is not None:
                with suppress(Exception):
                    bus.shutdown()

        async with self._bus_lock:
            if self._bus is bus:
                self._bus = None
            await asyncio.to_thread(shutdown)

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
