"""Base protocols and classes for entity models.

This module defines common interfaces and utilities shared across all entity models
to ensure consistency and type safety.
"""

from typing import Any, Protocol
import math

from .resource import ResourceTypes


class EntityProtocol(Protocol):
    """Protocol defining the common interface for all entity models.

    All entity models (Light, Sensor, Cover, etc.) should conform to this protocol
    to ensure consistent behavior across the codebase.

    Attributes:
        id: Unique identifier for the entity
        name: Human-readable name
        states: List of state topic patterns this entity subscribes to
        owner: ID of the owning device (if any)
        area: ID of the area this entity belongs to
        type: Resource type classification
    """

    id: str
    name: str
    states: list[str]
    owner: str | None
    area: str | None
    type: ResourceTypes

    def update(self, topic: str, data: dict[str, Any]) -> bool:
        """Update entity state from incoming message data.

        Args:
            topic: The message topic that triggered this update
            data: Payload data containing state updates

        Returns:
            True if the entity state was modified, False otherwise

        Raises:
            ValueError: If data validation fails
        """
        ...  # pylint: disable=unnecessary-ellipsis


def validate_numeric_value(
    value: Any, *, min_val: float | None = None, max_val: float | None = None
) -> float:
    """Validate and convert a numeric value.

    Args:
        value: Value to validate and convert
        min_val: Minimum allowed value (inclusive)
        max_val: Maximum allowed value (inclusive)

    Returns:
        Validated float value

    Raises:
        ValueError: If value cannot be converted or is out of range
        TypeError: If value is None
    """
    if value is None:
        raise TypeError("Value cannot be None")

    try:
        num_value = float(value)
    except (TypeError, ValueError) as e:
        raise ValueError(f"Cannot convert value to float: {value}") from e

    if not math.isfinite(num_value):
        raise ValueError("Numeric values must be finite")
    if min_val is not None and num_value < min_val:
        raise ValueError(f"Value {num_value} is below minimum {min_val}")
    if max_val is not None and num_value > max_val:
        raise ValueError(f"Value {num_value} is above maximum {max_val}")

    return num_value


def validate_byte_value(value: Any) -> int:
    """Validate an integer CAN channel value between 0 and 255."""
    number = validate_numeric_value(value, min_val=0, max_val=255)
    if not number.is_integer():
        raise ValueError("CAN channel values must be whole numbers")
    return int(number)


def validate_percentage(value: Any) -> int:
    """Validate and convert a percentage value (0-100).

    Args:
        value: Value to validate

    Returns:
        Integer percentage between 0 and 100

    Raises:
        ValueError: If value is not a valid percentage
    """
    num_value = validate_numeric_value(value, min_val=0, max_val=100)
    return int(round(num_value))
