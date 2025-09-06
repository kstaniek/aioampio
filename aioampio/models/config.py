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
    MSERVs = 10
    MROL4s = 3
    MINOC4p = 26


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
            except ValueError:
                raise ValueError(  # noqa: B904
                    f"state second part must be an integer, got: {parts[1]}"
                )
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

    platform: str = "sensor"
    device_class: str | None = None

    @field_validator("device_class", mode="after")
    @classmethod
    def validate_device_class(cls, value: str | None) -> str | None:
        allowed_device_classes = {
            "atmospheric_pressure",
            "temperature",
            "humidity",
            "illuminance",
            "aqi",
            "sound_pressure",
        }
        if value is not None and value not in allowed_device_classes:
            raise ValueError(
                f"Invalid device_class: {value}. Must be one of: {', '.join(sorted(allowed_device_classes))}"
            )
        return value


class LightCfg(PlatformCfg):
    """Configuration model for lights."""

    platform: str = "light"
    on: bool = False
    dimming: bool = False
    color: bool = False

    @model_validator(mode="after")
    def set_features(self) -> LightCfg:
        if has_state_prefix(self.states, "binout"):
            self.on = True
        if has_state_prefix(self.states, "aout"):
            self.dimming = True
        if has_state_prefix(self.states, "rgb"):
            self.color = True
        return self


class AlarmControlPanelCfg(PlatformCfg):
    """Configuration model for zones."""

    platform: str = "alarm_control_panel"


class TextCfg(PlatformCfg):
    """Configuration model for texts."""

    platform: str = "text"


class BinarySensorCfg(PlatformCfg):
    """Configuration model for texts."""

    platform: str = "binary_sensor"
    device_class: str | None = None

    @field_validator("device_class", mode="after")
    @classmethod
    def validate_device_class(cls, value: str | None) -> str | None:
        allowed_device_classes = {
            "motion",
            "window",
            "door",
            "lock",
            "carbon_monoxide",
            "moisture",
            "gas",
            "heat",
        }
        if value is not None and value not in allowed_device_classes:
            raise ValueError(
                f"Invalid device_class: {value}. Must be one of: {', '.join(sorted(allowed_device_classes))}"
            )
        return value


class SwitchCfg(PlatformCfg):
    """Configuration model for switches."""

    platform: str = "switch"
    on: bool = False

    device_class: str | None = None

    @field_validator("device_class", mode="after")
    @classmethod
    def validate_device_class(cls, value: str | None) -> str | None:
        allowed_device_classes = {"outlet", "switch"}
        if value is not None and value not in allowed_device_classes:
            raise ValueError(
                f"Invalid device_class: {value}. Must be one of: {', '.join(sorted(allowed_device_classes))}"
            )
        return value


class CoverCfg(PlatformCfg):
    """Configuration model for covers."""

    platform: str = "cover"


class ValveCfg(PlatformCfg):
    """Configuration model for valves."""

    platform: str = "valve"


class ClimateCfg(PlatformCfg):
    """Configuration model for climates."""

    platform: str = "climate"


class AreaCfg(BaseModel):
    """Configuration model for areas."""

    id: str
    name: str
    floor_name: str | None = None
    icon: str | None = None
    platform: str = "area"


class FloorCfg(BaseModel):
    """Configuration model for floors."""

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
        can_ids = [device.can_id for device in self.devices]
        duplicates = {f"{can_id:x}" for can_id in can_ids if can_ids.count(can_id) > 1}
        if duplicates:
            raise ValueError(
                f"Duplicate can_id values found: {', '.join(map(str, duplicates))}"
            )
        return self
