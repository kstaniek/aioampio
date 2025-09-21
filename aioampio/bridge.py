"""Ampio Bridge."""

import asyncio
from contextlib import suppress
import logging
import random
import time
from typing import Any


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


READ_TIMEOUT_S = 2.0


class AmpioBridge:  # pylint: disable=too-many-instance-attributes,too-many-public-methods
    """Ampio Bridge main class."""

    # --- Lifecycle: __init__, initialize(), start(), stop() -----------------

    def __init__(self, cfg: dict[str, Any], host: str, port: int) -> None:
        """Initialize the Ampio Bridge."""
        self._ampio_cfg = cfg
        self._host = host
        self._port = port

        self.logger = logging.getLogger(f"{__package__}[{self._host}]")

        self._config = AmpioConfig(self)

        self._reconnect_initial = 0.5
        self._reconnect_max = 30.0

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

        self._transport: asyncio.Task[None] | None = None
        self._bus: can.BusABC | None = None
        self._stop_event: asyncio.Event = asyncio.Event()

        self._proc_queue: asyncio.Queue[can.Message] = asyncio.Queue(maxsize=1000)
        self._rx_workers: list[asyncio.Task] = []

        self._reconnect_now: asyncio.Event = asyncio.Event()
        self._idle_reconnect_s: float | None = 60.0  # set None to disable
        self._rx_gap_reconnect_s: float | None = (
            10.0  # reconnect if no RX for this long after previously receiving
        )
        self._tx_error_reconnect_threshold = 3
        self._connected_since_mono: float | None = None
        self._connected_evt = asyncio.Event()
        self._max_no_rx_after_connect_s: float | None = 10.0  # None to disable

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
        self._rate_alpha = 0.6  # EMA smoothing factor (0..1), higher = snappier

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
        self._transport = asyncio.create_task(self._run(self._host, self._port))
        self.logger.info("Bridge started")

    async def stop(self) -> None:
        """Stop the bridge."""
        self._stop_event.set()
        if self._transport is None:
            return
        self._transport.cancel()
        with suppress(asyncio.CancelledError):
            await self._transport
        self._transport = None
        if self._bus is not None:
            with suppress(Exception):
                self._bus.shutdown()
            self._bus = None
        self.logger.info("Bridge stopped")

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
        return self._bus is not None and not self._stop_event.is_set()

    @property
    def reconnecting(self) -> bool:
        """Return True if a reconnect is pending/ongoing."""
        return self._reconnect_now.is_set()

    def trigger_reconnect(self, reason: str = "manual") -> None:
        """Trigger a reconnect as soon as possible."""
        if not self._reconnect_now.is_set():
            self.logger.info("Reconnect requested (%s)", reason)
            self._reconnect_now.set()

    async def send(self, can_id: int, data: bytes | memoryview) -> None:
        """Send a CAN frame (non-blocking for the event loop)."""
        bus = self._bus  # snapshot bus to avoid races with _bus = None
        if self._reconnect_now.is_set() or bus is None:
            self.logger.debug("TX dropped; reconnecting (bus unavailable)")
            return
        msg = can.Message(
            arbitration_id=can_id,
            data=bytes(data),
            is_extended_id=True,
            is_fd=False,
        )
        loop = asyncio.get_running_loop()
        try:
            await loop.run_in_executor(None, bus.send, msg, 1.0)
            self._tx_total += 1
            self._last_tx_mono = time.monotonic()
            self.logger.debug("TX id=0x%X len=%d", can_id, len(msg.data))
        except can.CanError as e:  # type: ignore[attr-defined]
            self._tx_errors += 1
            self._tx_error_streak += 1
            self.logger.error("TX failed; dropping frame id=0x%X: %s", can_id, e)
            if (
                "closed" in str(e).lower()
                or self._tx_error_streak >= self._tx_error_reconnect_threshold
            ):
                self._reconnect_now.set()
        else:
            # on success, reset tx error streak
            self._tx_error_streak = 0

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
        a = self._rate_alpha

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

    async def _run(self, host: str, port: int, channel: str = "can0") -> None:
        """Main bridge loop: connect, run session, reconnect on failure."""
        attempt = 0
        while not self._stop_event.is_set():
            bus: can.BusABC | None = None
            try:
                self.logger.info("Connecting to CAN at %s:%d", host, port)
                try:
                    bus = can.Bus(
                        interface="waveshare",
                        host=host,
                        port=port,
                        channel=channel,
                        receive_own_messages=False,
                        tcp_tune=True,
                        fd=False,
                    )
                except can.CanError as e:  # type: ignore[attr-defined]
                    self.logger.warning("Connect failed: %s", e)
                    bus = None

                if bus is None:
                    self._reconnects += 1
                    if self._stop_event.is_set():
                        break
                    delay = self._next_backoff(attempt)
                    attempt += 1
                    self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
                    await asyncio.sleep(delay)
                    continue

                self._log_connected(host, port, channel)
                had_rx = await self._run_session(bus)

            except asyncio.CancelledError:
                self.logger.info("Bridge task cancelled; shutting down")
                break
            except can.CanError as e:
                self.logger.warning("CAN error: %s", e)
            except Exception:  # pylint: disable=broad-exception-caught
                self.logger.exception("Error in CAN bus loop")
            finally:
                # session teardown was handled inside _run_session; nothing else here
                pass

            if self._stop_event.is_set():
                break

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
            maxsize=2000,
            drop_oldest=True,
            on_drop=self._inc_drop,
            on_enqueue=self._inc_enq,
        )
        notifier: can.Notifier | None = None
        try:
            notifier = can.Notifier(bus, [bounded.listener])
            self._start_rx_workers(n=1)
            while True:
                if self._should_reconnect():
                    self.logger.info("Reconnect requested; leaving reader loop")
                    break

                try:
                    msg = await asyncio.wait_for(bounded.get(), READ_TIMEOUT_S)
                    had_rx = True
                except asyncio.TimeoutError:
                    # heartbeat tick
                    if self._idle_watchdog():
                        continue
                    self.logger.debug(
                        "No CAN messages in the last %.1f seconds", READ_TIMEOUT_S
                    )
                    continue

                try:
                    self._proc_queue.put_nowait(msg)
                    self._rx_proc_queued += 1
                except asyncio.QueueFull:
                    self._rx_backpressure_drop += 1
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
            while not self._stop_event.is_set():
                try:
                    msg = await self._proc_queue.get()
                except asyncio.CancelledError:
                    break
                try:
                    self._rx_total += 1
                    self._last_rx_mono = time.monotonic()
                    await self._on_frame(msg)
                except asyncio.CancelledError:  # pylint: disable=try-except-raise
                    raise
                except Exception:  # pylint: disable=broad-exception-caught
                    self.logger.exception("RX worker %d failed", idx)

        self._rx_workers = [asyncio.create_task(worker(i)) for i in range(n)]

    async def _stop_rx_workers(self) -> None:
        for t in self._rx_workers:
            t.cancel()
        for t in self._rx_workers:
            with suppress(asyncio.CancelledError):
                await t
        self._rx_workers.clear()

    async def _on_frame(self, msg: can.Message) -> None:
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
        except Exception:  # pylint: disable=broad-exception-caught
            self.logger.exception(
                "Decoder failed for frame id=0x%X", msg.arbitration_id
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
            self._bus.set_filters(filters)  # type: ignore[call-arg]
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
        """Return True if we should force reconnect due to idleness/stall."""
        if self._idle_reconnect_s is None:
            return False

        now = time.monotonic()
        base = self._last_rx_mono or self._connected_since_mono or now
        idle = max(0.0, now - base)

        # 1) Stall: no RX at all since connect → quick reconnect
        if self._max_no_rx_after_connect_s is not None and self._last_rx_mono is None:
            since = now - (self._connected_since_mono or now)
            if since >= self._max_no_rx_after_connect_s:
                self.logger.warning(
                    "No RX within %.0fs after connect; forcing reconnect (notifier stall?)",
                    since,
                )
                self._reconnect_now.set()
                return True

        # 2) RX-gap: we *had* RX before, but we've seen nothing for too long
        if (
            self._rx_gap_reconnect_s is not None
            and self._last_rx_mono is not None
            and (now - self._last_rx_mono) >= self._rx_gap_reconnect_s
        ):
            gap = now - self._last_rx_mono
            self.logger.warning(
                "No RX for %.0fs since last message; forcing reconnect (rx-gap watchdog)",
                gap,
            )
            self._reconnect_now.set()
            return True

        # 3) Fallback: long idle since last RX or connect
        if idle >= self._idle_reconnect_s:
            self.logger.warning(
                "No RX for %.0fs; forcing reconnect (idle watchdog)", idle
            )
            self._reconnect_now.set()
            return True

        return False

    def _reset_connect_state(self) -> None:
        """Reset connection state on connect."""
        self._connected_evt.set()
        self._reconnect_now.clear()
        self._connected_since_mono = time.monotonic()

    def _clear_connect_state(self) -> None:
        """Clear connection state on disconnect."""
        self._connected_evt.clear()
        self._connected_since_mono = None

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

    def _log_connected(self, host: str, port: int, channel: str) -> None:
        """Log connection established."""
        self.logger.info(
            "Connected (iface=waveshare, channel=%s, host=%s, port=%d)",
            channel,
            host,
            port,
        )

    def _next_backoff(self, attempt: int) -> float:
        """Calculate the next backoff delay."""
        upper = min(self._reconnect_max, self._reconnect_initial * (2**attempt))
        return random.uniform(0.0, upper)

    # --- Internal counters/queue helpers ------------------------------------

    def _inc_drop(self) -> None:
        self._rx_backpressure_drop += 1

    def _inc_enq(self) -> None:
        self._rx_enqueued += 1
