"""Feature schemas."""

from dataclasses import dataclass


@dataclass
class OnFeature:
    """Represent `On` feature object used by Ampio."""

    on: bool


@dataclass
class DimmingFeature:
    """Represent `Dimming` feature object used by Ampio."""

    brightness: int


@dataclass
class ColorFeature:
    """Represent `Color` feature object used by Ampio."""

    red: int
    green: int
    blue: int
    white: int


@dataclass
class CoverPositionFeature:
    """Represent `Cover Position` feature object used by Ampio."""

    position: int = 0


@dataclass
class TiltPositionFeature:
    """Represent `Tilt Position` feature object used by Ampio."""

    position: int = 0


@dataclass
class ValvePositionFeature:
    """Represent `Valve Position` feature object used by Ampio."""

    position: int = 0
