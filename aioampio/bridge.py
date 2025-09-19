"""Ampio Bridge."""

import asyncio
from contextlib import suppress
import logging
import random
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
from .entity_manager import EntityManager


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

        self.entities = EntityManager(self)

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

    def _next_backoff(self, attempt: int) -> float:
        """Calculate the next backoff delay."""
        upper = min(self._reconnect_max, self._reconnect_initial * (2**attempt))
        return random.uniform(0.0, upper)

    async def _run(self, host: str, port: int, channel: str = "can0") -> None:
        """Run the transport."""
        attempt = 0

        async def reader_loop(bus: can.BusABC) -> None:
            """Read messages from the CAN bus."""
            reader = can.AsyncBufferedReader()
            listeners: list[can.notifier.MessageRecipient] = [
                reader,
            ]
            with can.Notifier(bus, listeners):
                while True:
                    try:
                        msg = await asyncio.wait_for(reader.get_message(), 10.0)
                        if msg is None:
                            return
                        await self._on_frame(msg)  # type: ignore
                    except asyncio.TimeoutError:
                        self.logger.warning(
                            "No CAN messages received in the last 10 seconds"
                        )
                        return

        while not self._stop_event.is_set():
            bus = None
            try:
                self.logger.info("Connecting to can at %s:%d", host, port)
                self._bus = bus = can.Bus(
                    interface="waveshare",
                    host=host,
                    port=port,
                    channel=channel,
                    receive_own_messages=False,
                    tcp_tune=True,
                    fd=False,
                )
                self.logger.info("Connected")
                attempt = 0  # reset backoff after successful connect

                # Apply device whitelist if configured
                self._apply_filters()

                await reader_loop(bus)
            except asyncio.CancelledError:
                self.logger.info("Bridge task cancelled; shutting down")
                break
            except Exception:  # pylint: disable=broad-exception-caught
                self.logger.exception("Error in CAN bus loop")
            finally:
                if bus is not None:
                    with suppress(Exception):
                        bus.shutdown()
                self._bus = None

            if self._stop_event.is_set():
                break

            delay = self._next_backoff(attempt)
            attempt += 1
            self.logger.info("Reconnecting to CAN bus in %.1f seconds", delay)
            await asyncio.sleep(delay)

    @property
    def connected(self) -> bool:
        """Return connection status."""
        return self._bus is not None and not self._stop_event.is_set()

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
            await self.entities.apply_message(m)

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
        if bus is None:
            self.logger.warning("TX dropped; bus not connected")
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
            self.logger.debug("TX id=0x%X len=%d", can_id, len(msg.data))
        except can.CanError as e:  # type: ignore[attr-defined]
            self.logger.error("TX failed; dropping frame id=0x%X: %s", can_id, e)

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
