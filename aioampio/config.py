"""This is the configuration module for the Ampio integration."""

from typing import TYPE_CHECKING, Any
from collections.abc import Iterator

from dacite import from_dict as dataclass_from_dict

from aioampio.models.alarm_control_panel import AlarmControlPanel
from aioampio.models.area import Area
from aioampio.models.climate import Climate
from aioampio.models.config import Config
from aioampio.models.cover import Cover
from aioampio.models.device import Device
from aioampio.models.floor import Floor
from aioampio.models.light import Light
from aioampio.models.sensor import Sensor
from aioampio.models.switch import Switch
from aioampio.models.text import Text
from aioampio.models.binary_sensor import BinarySensor
from aioampio.models.valve import Valve


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


def _norm_id(s: str) -> str:
    # keep it simple and predictable; adjust to your style
    return s.strip().lower().replace(" ", "_")


class AmpioConfig:
    """Configuration for Ampio integration."""

    def __init__(self, bridge: "AmpioBridge") -> None:
        self._bridge = bridge
        self._config: Config | None = None
        self._logger = bridge.logger.getChild("Config")
        self._items: dict[str, AmpioResource] = {}
        self._devices_by_id: dict[str, Device] = {}

    async def initialize(self, cfg: dict[str, Any]) -> None:
        """Initialize the configuration."""
        self._config = Config.model_validate(cfg)
        if getattr(self._config, "codecs", None):
            self._logger.warning(
                "Config 'codecs:' is deprecated/ignored; Ampio codec is built-in."
            )
        self._process_config()

    def _summary_counts(self) -> str:
        """Return a summary of item counts by type."""
        counts = {}
        for v in self._items.values():
            k = type(v).__name__
            counts[k] = counts.get(k, 0) + 1
        parts = ", ".join(f"{k}={n}" for k, n in sorted(counts.items()))
        return f"Config loaded: {len(self._items)} items ({parts})"

    def _validate_uniqueness(self) -> None:
        """Validate uniqueness of IDs and CAN IDs."""
        seen: set[str] = set()
        dups: list[str] = []
        for k in self._items:
            if k in seen:
                dups.append(k)
            else:
                seen.add(k)
        if dups:
            sample = ", ".join(sorted(dups)[:5])
            raise ValueError(
                f"Duplicate IDs in config ({len(dups)} total). Examples: {sample}"
            )

        # Optional: check for duplicate CAN IDs (29-bit only) across devices
        dev_ids = [it.can_id for it in self._items.values() if isinstance(it, Device)]
        bad = [cid for cid in dev_ids if not (0 <= cid <= 0x1FFFFFFF)]
        if bad:
            self._logger.warning(
                "Some device CAN IDs are not 29-bit: %s",
                ", ".join(f"0x{b:X}" for b in bad),
            )

    def _process_config(self) -> None:
        """Process and validate the configuration."""
        if self._config is None:
            raise RuntimeError("Configuration not initialized")

        for floor in self._config.floors:
            floor_item: Floor = dataclass_from_dict(
                Floor, floor.model_dump(exclude_unset=True)
            )
            self._items[floor_item.id] = floor_item
            for area in floor.areas:
                area.id = f"{floor.id}_{_norm_id(area.id)}"
                area_item = dataclass_from_dict(
                    Area, area.model_dump(exclude_unset=True)
                )
                area_item.floor_name = floor.name
                self._items[area_item.id] = area_item

        for area in self._config.areas:
            area.id = _norm_id(area.id)
            item: Area = dataclass_from_dict(Area, area.model_dump(exclude_unset=True))
            self._items[item.id] = item

        for device in self._config.devices:
            device.id = f"{device.can_id:08x}"
            device_item: Device = dataclass_from_dict(
                Device, device.model_dump(exclude_unset=True)
            )
            self._items[device_item.id] = device_item
            self._devices_by_id[device_item.id] = device_item

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
                    prefix = f"{device.can_id:08x}_"
                    sid = _norm_id(subitem.id)
                    if not sid.startswith(prefix):
                        sid = prefix + sid
                    subitem.id = sid
                    item_obj = dataclass_from_dict(
                        cls, subitem.model_dump(exclude_unset=True)
                    )
                    item_obj.owner = device.id
                    self._items[item_obj.id] = item_obj
        self._validate_uniqueness()
        self._logger.info(self._summary_counts())

    @property
    def whitelist_can_ids(self) -> set[int]:
        """Return the set of CAN IDs used by devices in the config."""
        return {d.can_id for d in self._devices_by_id.values()}

    def get(
        self, id: str, *, type_: type[AmpioResource] | None = None
    ) -> AmpioResource:
        """Get item by id, optionally checking its type."""
        obj = self._items[id]
        if type_ is not None and not isinstance(obj, type_):
            raise TypeError(f"{id} is {type(obj).__name__}, not {type_.__name__}")
        return obj

    def of_type(self, type_: type[AmpioResource]) -> list[AmpioResource]:
        """Get all items of a specific type."""
        return [v for v in self._items.values() if isinstance(v, type_)]

    def __getitem__(self, id: str) -> AmpioResource:
        """Get item by id."""
        return self._items[id]

    def __iter__(self) -> Iterator[AmpioResource]:
        """Return an iterator over the items."""
        return iter(self._items.values())

    def __contains__(self, id: str) -> bool:
        """Check if the item is in the collection."""
        return id in self._items
