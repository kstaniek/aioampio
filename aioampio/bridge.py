"""Ampio Bridge."""

import asyncio
from contextlib import suppress
import logging
import random
import time
from typing import Any


import can

from aioampio.config import AmpioConfig
from aioampio.controllers.alarm_control_panels import AlarmControlPanelsController
from aioampio.controllers.areas import AreasController
from aioampio.controllers.binary_sensor import BinarySensorsController
from aioampio.controllers.climates import ClimatesController
from aioampio.controllers.covers import CoversController
from aioampio.controllers.sensor import SensorsController
from aioampio.controllers.switch import SwitchesController
from aioampio.controllers.text import TextsController
from aioampio.controllers.floors import FloorsController
from aioampio.controllers.valves import ValvesController

from .controllers.lights import LightsController
from .controllers.devices import DevicesController

from .codec.registry import registry
from .codec.base import CANFrame
from .state_store import StateStore
from .helpers.rx_reader import BoundedAsyncCanReader


READ_TIMEOUT_S = 2.0


class AmpioBridge:  # pylint: disable=too-many-instance-attributes
    """Ampio Bridge main class."""

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
        self._connected_since_mono: float | None = None

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

    # def set_filters(self) -> None:
    #     """Set CAN filters based on device whitelist from configuration."""
    #     self._whitelist = {
    #         item.can_id  # type: ignore  # noqa: PGH003
    #         for item in self._config
    #         if item.type == ResourceTypes.DEVICE and hasattr(item, "can_id")
    #     }
    #     if self._whitelist:
    #         # filters = [(can_id, 0xFE, None) for can_id in self._whitelist]
    #         filters = [(can_id, None, None) for can_id in self._whitelist]
    #         self.transport.set_filters(filters)
    #         self.logger.info(
    #             "Device whitelist applied for %i devices", len(self._whitelist)
    #         )

    async def initialize(self) -> None:
        """Initialize the bridge."""
        await self._config.initialize(self._ampio_cfg)
        # self.set_filters()

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

    def _inc_drop(self) -> None:
        self._rx_backpressure_drop += 1

    def _inc_enq(self) -> None:
        self._rx_enqueued += 1

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

    def _next_backoff(self, attempt: int) -> float:
        """Calculate the next backoff delay."""
        upper = min(self._reconnect_max, self._reconnect_initial * (2**attempt))
        return random.uniform(0.0, upper)

    async def _run(self, host: str, port: int, channel: str = "can0") -> None:  # pylint: disable=too-many-nested-blocks,too-many-branches,too-many-statements
        attempt = 0
        while not self._stop_event.is_set():
            bus = None
            try:
                try:
                    self.logger.info("Connecting to CAN at %s:%d", host, port)
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
                else:
                    self._bus = bus
                    self.logger.info("Connected")
                    self._reconnect_now.clear()
                    self._connected_since_mono = time.monotonic()
                    attempt = 0
                    self._apply_filters()

                    loop = asyncio.get_running_loop()
                    bounded = BoundedAsyncCanReader(
                        loop=loop,
                        maxsize=2000,
                        drop_oldest=True,  # latest state wins
                        on_drop=self._inc_drop,
                        on_enqueue=self._inc_enq,
                    )
                    self._start_rx_workers(n=2)  # set to 1 if strict ordering required

                    with can.Notifier(bus, [bounded.listener]):
                        while True:
                            if (
                                self._stop_event.is_set()
                                or self._reconnect_now.is_set()
                            ):
                                self.logger.info(
                                    "Reconnect requested; leaving reader loop"
                                )
                                break
                            try:
                                msg = await asyncio.wait_for(
                                    bounded.get(), READ_TIMEOUT_S
                                )
                            except asyncio.TimeoutError:
                                # Idle tick: check watchdog
                                if self._idle_reconnect_s is not None:
                                    now = time.monotonic()
                                    base = (
                                        self._last_rx_mono
                                        or self._connected_since_mono
                                        or now
                                    )
                                    idle = max(0.0, now - base)
                                    if idle >= self._idle_reconnect_s:
                                        self.logger.warning(
                                            "No RX for %.0fs; forcing reconnect", idle
                                        )
                                        self._reconnect_now.set()
                                        continue
                                self.logger.debug(
                                    "No CAN messages in the last %.1f seconds",
                                    READ_TIMEOUT_S,
                                )
                                continue
                            # Stage-2 bounded queue (processing)
                            try:
                                self._proc_queue.put_nowait(msg)
                                self._rx_proc_queued += 1
                            except asyncio.QueueFull:
                                # processing saturated: drop newest
                                self._rx_backpressure_drop += 1

            except asyncio.CancelledError:
                self.logger.info("Bridge task cancelled; shutting down")
                break
            except can.CanError as e:
                # We already log a concise warning above when opening fails,
                # but if other CAN ops raise, keep it concise too:
                self.logger.warning("CAN error: %s", e)
            except Exception:  # pylint: disable=broad-exception-caught
                self.logger.exception("Error in CAN bus loop")
            finally:
                await self._stop_rx_workers()
                if bus is not None:
                    with suppress(Exception):
                        bus.shutdown()
                self._bus = None
                self._connected_since_mono = None
                while not self._proc_queue.empty():
                    with suppress(asyncio.QueueEmpty):
                        self._proc_queue.get_nowait()

            if self._stop_event.is_set():
                break
            self._reconnects += 1
            delay = self._next_backoff(attempt)
            attempt += 1
            self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
            await asyncio.sleep(delay)

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._bus is not None and not self._stop_event.is_set()

    @property
    def metrics(self) -> dict[str, Any]:
        """Return connection and message metrics."""
        now = time.monotonic()
        return {
            "connected": self.connected,
            "reconnects": self._reconnects,
            "rx_total": self._rx_total,
            "rx_enqueued": self._rx_enqueued,  # at CAN→loop boundary
            "rx_proc_queued": self._rx_proc_queued,  # accepted for processing
            "rx_dropped": self._rx_backpressure_drop,  # dropped at either stage
            "tx_total": self._tx_total,
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
        }

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
            self.logger.error("TX failed; dropping frame id=0x%X: %s", can_id, e)
            if "closed" in str(e).lower():
                self._reconnect_now.set()

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
