"""This is the configuration module for the Ampio integration."""

from typing import TYPE_CHECKING, Any
from collections.abc import Iterator

from dacite import from_dict as dataclass_from_dict

from aioampio.models.alarm_control_panel import AlarmControlPanel
from aioampio.models.area import Area
from aioampio.models.climate import Climate
from aioampio.models.config import Config, OutputCfg
from aioampio.models.cover import Cover
from aioampio.models.device import Device
from aioampio.models.floor import Floor
from aioampio.models.light import Light
from aioampio.models.sensor import Sensor
from aioampio.models.switch import Switch
from aioampio.models.text import Text
from aioampio.models.binary_sensor import BinarySensor
from aioampio.models.valve import Valve
from aioampio.codec.registry import registry


if TYPE_CHECKING:
    from .bridge import AmpioBridge

type AmpioResource = (
    Device
    | Floor
    | Light
    | Sensor
    | Switch
    | Text
    | BinarySensor
    | Valve
    | Cover
    | Climate
    | Area
    | AlarmControlPanel
)


class AmpioConfig:
    """Configuration for Ampio integration."""

    def __init__(self, bridge: "AmpioBridge") -> None:
        self._bridge = bridge
        self._config: Config | None = None
        self._logger = bridge.logger.getChild("Config")
        self._items: dict[str, AmpioResource] = {}

    async def initialize(self, cfg: dict[str, Any]) -> None:
        """Initialize the configuration."""
        self._config = Config.model_validate(cfg)
        await registry().load_modules([c.module for c in self._config.codecs])
        self._process_config()

    def _process_config(self) -> None:
        if self._config is None:
            raise RuntimeError("Configuration not initialized")

        for floor in self._config.floors:
            floor_item: Floor = dataclass_from_dict(Floor, floor.model_dump())
            self._items[floor_item.id] = floor_item
            for area in floor.areas:
                area.id = f"{floor.id}_{area.id}"
                area_item = dataclass_from_dict(Area, area.model_dump())
                area_item.floor_name = floor.name
                self._items[area_item.id] = area_item

        for area in self._config.areas:
            item: Area = dataclass_from_dict(Area, area.model_dump())
            self._items[item.id] = item

        for device in self._config.devices:
            device.id = f"{device.can_id:08x}"
            device_item: Device = dataclass_from_dict(Device, device.model_dump())
            self._items[device_item.id] = device_item

            # Define subresources and their classes
            subresources = [
                ("lights", Light),
                ("alarm_control_panels", AlarmControlPanel),
                ("texts", Text),
                ("binary_sensors", BinarySensor),
                ("sensors", Sensor),
                ("switches", Switch),
                ("covers", Cover),
                ("valves", Valve),
                ("climates", Climate),
            ]

            for attr, cls in subresources:
                for subitem in getattr(device, attr, []):
                    subitem.id = f"{device.can_id:08x}_{subitem.id}"
                    item_obj = dataclass_from_dict(cls, subitem.model_dump())
                    item_obj.owner = device.id
                    self._items[item_obj.id] = item_obj

    def __getitem__(self, id: str) -> AmpioResource:
        """Get item by id."""
        return self._items[id]

    def __iter__(self) -> Iterator[AmpioResource]:
        """Return an iterator over the items."""
        return iter(self._items.values())

    def __contains__(self, id: str) -> bool:
        """Check if the item is in the collection."""
        return id in self._items

    @property
    def outputs(self) -> list[OutputCfg]:
        """Return the configured outputs."""
        if self._config is None:
            raise RuntimeError("Configuration not initialized")
        return self._config.outputs
