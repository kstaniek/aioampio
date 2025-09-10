"""Configuration loading and validation."""

from __future__ import annotations

from enum import Enum, unique

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    model_validator,
    field_validator,
)

state_value_types = {
    "bin",
    "bout",
    "aint",
    "aout",
    "rgb",
    "s16b",
    "s16b10000",
    "temperature",
    "binout",
    "response",
    "arming",
    "arming_10s",
    "armed",
    "breached",
    "alarm",
    "flag",
    "datetime",
    "heating",
    "zone",
}


def has_state_prefix(states: str | list[str], prefixes: str | list[str]) -> bool:
    """Check if any state starts with any of the given prefixes."""
    if isinstance(prefixes, str):
        prefixes = [prefixes]
    if isinstance(states, str):
        return any(states.startswith(prefix) for prefix in prefixes)
    return any(any(state.startswith(prefix) for prefix in prefixes) for state in states)


class OutputCfg(BaseModel):
    """Configuration model for outputs."""

    type: str
    format: str | None = None


class CodecCfg(BaseModel):
    """Configuration model for codecs."""

    module: str  # python module path to import for codec registration


@unique
class DeviceType(Enum):
    """Enumeration of device types."""

    MRGBW = 12
    MSENS = 44
    MLED = 17
    MDIM = 5
    MCOM = 25
    MRT16S = 22
    MREL8S = 4
    MSERVS = 10
    MROL4S = 3
    MINOC4P = 26


class PlatformCfg(BaseModel):
    """Configuration model for platforms."""

    model_config = ConfigDict(arbitrary_types_allowed=True)

    id: str
    name: str
    states: str | list[str]
    area: str | None = None

    @field_validator("states", mode="before")
    @classmethod
    def ensure_state_lowercase(cls, v: list[str] | str) -> list[str]:
        """Normalize state(s) to lowercase; keep original shape (str vs list[str])."""

        def validate_state(state: str) -> str:
            """Validate individual state string."""
            state = state.strip().lower()
            parts = state.split(".")
            if len(parts) != 2:
                raise ValueError(
                    f"state must have exactly 2 parts separated by '.', got: {state}"
                )
            if parts[0] not in state_value_types:
                raise ValueError(
                    f"state prefix must be one of {state_value_types}, got: {parts[0]}"
                )
            try:
                int(parts[1])
            except ValueError as e:
                raise ValueError(
                    f"state second part must be an integer, got: {parts[1]}"
                ) from e
            return state

        if isinstance(v, str):
            return [validate_state(v)]
        if isinstance(v, list):
            out = []
            for i, item in enumerate(v):
                if not isinstance(item, str):
                    raise TypeError(
                        f"state[{i}] must be a string, got {type(item).__name__}"
                    )
                out.append(validate_state(item))
            return out
        raise TypeError(f"state must be str or list[str], got {type(v).__name__}")


class DeviceCfg(BaseModel):
    """Configuration model for devices."""

    model_config = ConfigDict(extra="forbid")

    can_id: int = Field(0, ge=0, le=0x1FFFFFFF)
    name: str
    model: DeviceType
    id: str | None = None
    pcb: int = 0
    sw_version: int = 0
    area: str | None = None
    binary_sensors: list[BinarySensorCfg] = Field(default_factory=list)
    sensors: list[SensorCfg] = Field(default_factory=list)
    lights: list[LightCfg] = Field(default_factory=list)
    covers: list[CoverCfg] = Field(default_factory=list)
    alarm_control_panels: list[AlarmControlPanelCfg] = Field(default_factory=list)
    texts: list[TextCfg] = Field(default_factory=list)
    switches: list[SwitchCfg] = Field(default_factory=list)
    valves: list[ValveCfg] = Field(default_factory=list)
    climates: list[ClimateCfg] = Field(default_factory=list)


class SensorCfg(PlatformCfg):
    """Configuration model for sensors."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "sensor"
    device_class: str | None = None

    @field_validator("device_class", mode="after")
    @classmethod
    def validate_device_class(cls, value: str | None) -> str | None:
        """Validate device class."""
        allowed_device_classes = {
            "aqi",
            "atmospheric_pressure",
            "battery",
            "carbon_dioxide",
            "carbon_monoxide",
            "current",
            "data_rate",
            "data_size",
            "date",
            "distance",
            "duration",
            "energy",
            "energy_storage",
            "frequency",
            "gas",
            "humidity",
            "illuminance",
            "irradiance",
            "moisture",
            "monetary",
            "nitrogen_dioxide",
            "nitrogen_monoxide",
            "nitrous_oxide",
            "ozone",
            "ph",
            "pm1",
            "pm10",
            "pm25",
            "power",
            "power_factor",
            "precipitation",
            "precipitation_intensity",
            "pressure",
            "reactive_power",
            "signal_strength",
            "sound_pressure",
            "speed",
            "sulphur_dioxide",
            "temperature",
            "timestamp",
            "volatile_organic_compounds",
            "voltage",
            "volume",
            "water",
            "weight",
            "wind_speed",
        }
        if value is not None and value not in allowed_device_classes:
            raise ValueError(
                f"Invalid device_class: {value}. Must be one of: {', '.join(sorted(allowed_device_classes))}"
            )
        return value


class LightCfg(PlatformCfg):
    """Configuration model for lights."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "light"
    on: bool = False
    dimming: bool = False
    color: bool = False

    @model_validator(mode="after")
    def set_features(self) -> LightCfg:
        """Set light features based on states if not explicitly set."""
        if has_state_prefix(self.states, "binout"):
            self.on = True
        if has_state_prefix(self.states, "aout"):
            self.dimming = True
        if has_state_prefix(self.states, "rgb"):
            self.color = True
        return self


class AlarmControlPanelCfg(PlatformCfg):
    """Configuration model for zones."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "alarm_control_panel"


class TextCfg(PlatformCfg):
    """Configuration model for texts."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "text"


class BinarySensorCfg(PlatformCfg):
    """Configuration model for texts."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "binary_sensor"
    device_class: str | None = None

    @field_validator("device_class", mode="after")
    @classmethod
    def validate_device_class(cls, value: str | None) -> str | None:
        """Validate device class."""
        allowed_device_classes = {
            "battery",
            "battery_charging",
            "carbon_monoxide",
            "cold",
            "connectivity",
            "door",
            "garage_door",
            "gas",
            "heat",
            "light",
            "lock",
            "moisture",
            "motion",
            "moving",
            "occupancy",
            "opening",
            "plug",
            "power",
            "presence",
            "problem",
            "running",
            "safety",
            "smoke",
            "sound",
            "tamper",
            "update",
            "vibration",
            "window",
        }
        if value is not None and value not in allowed_device_classes:
            raise ValueError(
                f"Invalid device_class: {value}. Must be one of: {', '.join(sorted(allowed_device_classes))}"
            )
        return value


class SwitchCfg(PlatformCfg):
    """Configuration model for switches."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "switch"
    on: bool = False

    device_class: str | None = None

    @field_validator("device_class", mode="after")
    @classmethod
    def validate_device_class(cls, value: str | None) -> str | None:
        """Validate device class."""
        allowed_device_classes = {"outlet", "switch"}
        if value is not None and value not in allowed_device_classes:
            raise ValueError(
                f"Invalid device_class: {value}. Must be one of: {', '.join(sorted(allowed_device_classes))}"
            )
        return value


class CoverCfg(PlatformCfg):
    """Configuration model for covers."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "cover"
    device_class: str | None = None

    @field_validator("device_class", mode="after")
    @classmethod
    def validate_device_class(cls, value: str | None) -> str | None:
        """Validate device class."""
        allowed_device_classes = {
            "awning",
            "blind",
            "curtain",
            "damper",
            "door",
            "garage",
            "gate",
            "shade",
            "shutter",
            "window",
        }
        if value is not None and value not in allowed_device_classes:
            raise ValueError(
                f"Invalid device_class: {value}. Must be one of: {', '.join(sorted(allowed_device_classes))}"
            )
        return value


class ValveCfg(PlatformCfg):
    """Configuration model for valves."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "valve"


class ClimateCfg(PlatformCfg):
    """Configuration model for climates."""

    model_config = ConfigDict(extra="forbid")

    platform: str = "climate"


class AreaCfg(BaseModel):
    """Configuration model for areas."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    floor_name: str | None = None
    icon: str | None = None
    platform: str = "area"


class FloorCfg(BaseModel):
    """Configuration model for floors."""

    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    level: int = 0
    platform: str = "floor"

    areas: list[AreaCfg] = Field(default_factory=list)


class Config(BaseModel):
    """Configuration model for AmpioBridge."""

    model_config = ConfigDict(extra="forbid")

    floors: list[FloorCfg] = Field(default_factory=list)
    areas: list[AreaCfg] = Field(default_factory=list)
    outputs: list[OutputCfg] = Field(default_factory=list)
    codecs: list[CodecCfg] = Field(default_factory=list)
    devices: list[DeviceCfg] = Field(default_factory=list)

    @model_validator(mode="after")
    def check_unique_can_id(self) -> Config:
        """Ensure all device can_id values are unique."""
        can_ids = [device.can_id for device in self.devices]  # pylint: disable=not-an-iterable
        duplicates = {f"{can_id:x}" for can_id in can_ids if can_ids.count(can_id) > 1}
        if duplicates:
            raise ValueError(
                f"Duplicate can_id values found: {', '.join(map(str, duplicates))}"
            )
        return self
