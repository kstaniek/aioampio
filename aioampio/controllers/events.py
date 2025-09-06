"""Handle and distribute events."""

from collections.abc import Callable
from enum import Enum

from aioampio.models.resource import ResourceTypes


class EventType(Enum):
    """Enum with possible events."""

    RESOURCE_ADDED = "add"
    RESOURCE_UPDATED = "update"
    RESOURCE_DELETED = "delete"

    ENTITY_UPDATED = "entity_updated"


EventCallBackType = Callable[[EventType, dict | None], None]
EventSubscriptionType = tuple[
    EventCallBackType,
    "tuple[EventType] | None",
    "tuple[ResourceTypes] | None",
]
