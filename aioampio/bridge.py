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


_LOGGER = logging.getLogger(__name__)


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
        self._transport = asyncio.create_task(self._run(self._host, self._port))
        # await self._run(self._host, self._port)
        _LOGGER.info("Bridge started")

    async def stop(self) -> None:
        """Stop the bridge."""
        if self._transport is None:
            return
        self._transport.cancel()

        with suppress(asyncio.CancelledError):
            await self._transport
            self._transport = None

    def _next_backoff(self, attempt: int) -> float:
        """Calculate the next backoff delay."""
        upper = min(self._reconnect_max, self._reconnect_initial * (2**attempt))
        return random.uniform(0.0, upper)

    async def _run(self, host: str, port: int, channel: str = "can0") -> None:
        """Run the transport."""
        stop = asyncio.Event()
        attempt = 0

        async def reader_loop(bus: can.BusABC) -> None:
            """Read messages from the CAN bus."""
            reader = can.AsyncBufferedReader()
            listeners: list[can.notifier.MessageRecipient] = [
                reader,
            ]
            try:
                with can.Notifier(bus, listeners):
                    while True:
                        msg = await asyncio.wait_for(reader.get_message(), 10.0)
                        if msg is None:
                            return
                        await self._on_frame(msg)  # type: ignore
            except asyncio.TimeoutError:
                _LOGGER.warning("No CAN messages received in the last 10 seconds")

        while not stop.is_set():
            try:
                _LOGGER.info("Connecting to can at %s:%d", host, port)
                self._bus = bus = can.interface.Bus(
                    interface="waveshare",
                    host=host,
                    port=port,
                    channel=channel,
                    receive_own_messages=False,
                    tcp_tune=True,
                    fd=False,
                )
                _LOGGER.info("Connected")
                await reader_loop(bus)
            except Exception as exc:  # pylint: disable=broad-except
                _LOGGER.error("Error in CAN bus loop: %s", exc)
            finally:
                with suppress(Exception):
                    bus.shutdown()
            delay = self._next_backoff(attempt)
            attempt += 1
            _LOGGER.info("Reconnecting to CAN bus in %.1f seconds", delay)
            await asyncio.sleep(delay)

    async def _on_frame(self, msg: can.Message) -> None:
        """Handle incoming CAN frame."""
        if msg.is_extended_id is False:
            self.logger.warning("Ignoring non-extended CAN frame: %s", msg)
            return
        if msg.is_remote_frame:
            self.logger.warning("Ignoring remote CAN frame: %s", msg)
            return
        if msg.dlc != len(msg.data):
            self.logger.warning("Ignoring CAN frame with invalid DLC: %s", msg)
            return
        frame = CANFrame(can_id=msg.arbitration_id, data=memoryview(msg.data))
        msgs = registry().decode(frame)
        if msgs:
            # store/update entity state
            for m in msgs:
                await self.entities.apply_message(m)

    async def send(self, can_id: int, data: bytes | memoryview) -> None:
        """Send a CAN frame."""
        print("TX", data.hex())

        if self._transport is None:
            return
        if self._bus is None:
            return
        msg = can.Message(
            arbitration_id=can_id,
            data=data,
            is_extended_id=True,
            is_fd=False,
        )
        try:
            self._bus.send(msg, timeout=1.0)
        except can.CanError as e:
            self.logger.error("TX failed; dropping frame id=0x%X: %s", can_id, e)
        # await self.transport.send(frame.can_id, frame.data)  # type: ignore

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
