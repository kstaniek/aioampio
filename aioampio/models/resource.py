"""Generic/base resource models."""

from enum import Enum


class ResourceTypes(Enum):
    """Type of the supported Ampio resources."""

    DEVICE = "device"
    BRIDGE = "bridge"
    LIGHT = "light"
    ALARM_CONTROL_PANEL = "alarm_control_panel"
    TEXT = "text"
    BINARY_SENSOR = "binary_sensor"
    SENSOR = "sensor"
    AREA = "area"
    FLOOR = "floor"
    SWITCH = "switch"
    COVER = "cover"
    VALVE = "valve"
    CLIMATE = "climate"
