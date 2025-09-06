"""Ampio Bridge."""

import asyncio
import logging

from caneth import CANFrame

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
from aioampio.outputs.stdout import StdoutOutput

from .controllers.lights import LightsController
from .controllers.devices import DevicesController

from .codec.registry import registry
from .entity_manager import EntityManager
from .transport import CanethTransport
from .models.resource import ResourceTypes


class AmpioBridge:  # pylint: disable=too-many-instance-attributes
    """Ampio Bridge main class."""

    def __init__(self, cfg_path: str, host: str, port: int) -> None:
        """Initialize the Ampio Bridge."""
        self._host = host
        self._port = port
        self._cfg_path = cfg_path

        self.logger = logging.getLogger(f"{__package__}[{self._host}]")

        self.config = AmpioConfig(self)

        self.transport = CanethTransport(self._host, self._port)
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

        self._outputs: list[StdoutOutput] = []
        self._whitelist: set[int] = set()

    def set_filters(self) -> None:
        """Set CAN filters based on device whitelist from configuration."""
        self._whitelist: set[int] = {
            item.can_id  # type: ignore  # noqa: PGH003
            for item in self.config
            if item.type == ResourceTypes.DEVICE and hasattr(item, "can_id")
        }
        if self._whitelist:
            # filters = [(can_id, 0xFE, None) for can_id in self._whitelist]
            filters = [(can_id, None, None) for can_id in self._whitelist]
            self.transport.set_filters(filters)
            self.logger.info(
                "Device whitelist applied for %i devices", len(self._whitelist)
            )

    def initialize_outputs(self) -> None:
        """Initialize output handlers based on configuration."""
        for out in self.config.outputs:
            if out.type == "stdout":
                self._outputs.append(StdoutOutput(fmt=out.format))

    async def initialize(self) -> None:
        """Initialize the bridge."""
        await self.config.initialize(self._cfg_path)
        self.set_filters()
        self.initialize_outputs()

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
        self.transport.on_frame(self._on_frame)
        await self.transport.start()

    async def stop(self) -> None:
        """Stop the bridge."""
        await self.transport.close()

    async def _on_frame(self, frame: CANFrame) -> None:
        """Handle incoming CAN frame."""
        msgs = registry().decode(frame)
        if msgs:
            # store/update entity state
            for msg in msgs:
                await self.entities.apply_message(msg)
            # emit outputs for visibility
            for out in self._outputs:
                for msg in msgs:
                    out.emit_msg(msg)
        else:
            for out in self._outputs:
                out.emit_raw(frame)

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
