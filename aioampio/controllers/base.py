"""Base controller for managing Ampio entities."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Iterator
from contextlib import suppress
import inspect
import struct
from dataclasses import asdict
from typing import Any, Final, Protocol, TYPE_CHECKING, TypeVar

from dacite import from_dict as dataclass_from_dict

from aioampio.controllers.events import EventCallBackType, EventType
from aioampio.controllers.utils import generate_multican_payload, get_entity_index
from aioampio.models.device import Device
from aioampio.models.resource import ResourceTypes

if TYPE_CHECKING:
    from aioampio.bridge import AmpioBridge

# ---------------------------------------------------------------------
# Types & constants
# ---------------------------------------------------------------------


class _Updatable(Protocol):
    """Protocol for resources that can be updated with topic data."""

    def update(self, topic: str, data: dict) -> None:
        """Update the resource with new data from a topic."""


EventSubscriptionType = tuple[EventCallBackType, tuple[EventType, ...] | None]

ID_FILTER_ALL: Final[str] = "*"
CTRL_CAN_ID: Final[int] = 0x0F000000
_NOOP: Final[tuple[EventType, str | None, Any | None]] = (
    EventType.RESOURCE_UPDATED,
    None,
    None,
)

AmpioResource = TypeVar("AmpioResource", bound=_Updatable)


class AmpioResourceController[AmpioResource]:
    """Base controller for managing Ampio entities."""

    item_type: ResourceTypes | None = None
    item_cls: type[AmpioResource] | None = None

    def __init__(self, bridge: "AmpioBridge") -> None:
        """Initialize the controller."""
        self._bridge = bridge
        self._items: dict[str, AmpioResource] = {}
        # topic -> item_id
        self._topics: dict[str, str] = {}
        self._logger = bridge.logger.getChild(self.item_type.value)  # type: ignore[arg-type]
        self._subscribers: dict[str, list[EventSubscriptionType]] = {ID_FILTER_ALL: []}
        self._initialized = False
        # item_id -> list[unsubscribe]
        self._unsubs: dict[str, list[Callable[[], None]]] = {}

        # Event dispatcher
        self._dispatch: dict[
            EventType, Callable[[dict], tuple[EventType, str | None, Any | None]]
        ] = {
            EventType.RESOURCE_ADDED: self._evt_resource_added,
            EventType.RESOURCE_DELETED: self._evt_resource_deleted,
            EventType.RESOURCE_UPDATED: self._evt_resource_updated,
            # Normalized to RESOURCE_UPDATED for notifications:
            EventType.ENTITY_UPDATED: self._evt_entity_updated,
        }

    # ---------------------------------------------------------------------
    # Public API
    # ---------------------------------------------------------------------

    @property
    def items(self) -> list[AmpioResource]:
        """Return a list of all items."""
        return list(self._items.values())

    async def initialize(self) -> None:
        """Initialize the controller by loading existing resources."""
        resources = [x for x in self._bridge.config if x.type == self.item_type]
        for resource in resources:
            await self._handle_event(EventType.RESOURCE_ADDED, asdict(resource))
        self._initialized = True

    def subscribe(
        self,
        callback: EventCallBackType,
        id_filter: str | tuple[str, ...] | None = None,
        event_filter: EventType | tuple[EventType, ...] | None = None,
    ) -> Callable[[], None]:
        """Subscribe to status changes for this resource type."""
        if event_filter is not None and not isinstance(event_filter, tuple):
            event_filter = (event_filter,)

        if id_filter is None:
            id_filter = (ID_FILTER_ALL,)
        elif not isinstance(id_filter, tuple):
            id_filter = (id_filter,)

        sub: EventSubscriptionType = (callback, event_filter)
        for id_key in id_filter:
            self._subscribers.setdefault(id_key, []).append(sub)

        def unsubscribe() -> None:
            for id_key in id_filter:  # type: ignore[assignment]
                lst = self._subscribers.get(id_key)
                if not lst:
                    continue
                with suppress(ValueError):
                    lst.remove(sub)
                if not lst and id_key != ID_FILTER_ALL:
                    # keep ALL bucket alive; trim others when empty
                    self._subscribers.pop(id_key, None)

        return unsubscribe

    def get_device(self, id: str) -> Device | None:
        """Return the device associated with the given resource."""
        item = self.get(id)
        if self.item_type == ResourceTypes.DEVICE:
            return item if isinstance(item, Device) else None
        owner = getattr(item, "owner", None) if item is not None else None
        dev = self._bridge.devices.get(owner) if owner else None
        return dev if isinstance(dev, Device) else None

    def get(self, id: str, default: Any = None) -> AmpioResource | None:
        """Get item by id."""
        return self._items.get(id, default)

    def __getitem__(self, id: str) -> AmpioResource:
        """Get item by id."""
        return self._items[id]

    def __iter__(self) -> Iterator[AmpioResource]:
        """Return an iterator over the items."""
        return iter(self._items.values())

    def __contains__(self, id: str) -> bool:
        """Check if the item is in the collection."""
        return id in self._items

    # ---------------------------------------------------------------------
    # Event handling
    # ---------------------------------------------------------------------

    def _id_of(self, data: dict) -> str | None:
        """Centralized accessor for event item id."""
        return data.get("id")

    def _subscribe_topics_for(
        self, item_id: str, owner: str, topics: list[str]
    ) -> None:
        """Subscribe to per-entity state topics and remember unsub handles."""
        if not topics:
            return
        unsubs: list[Callable[[], None]] = []
        for t in topics:
            full = f"{owner}.{t}"
            self._topics[full] = item_id
            unsubs.append(
                self._bridge.state_store.on_change(self._handle_event, topic=full)
            )
        if unsubs:
            self._unsubs.setdefault(item_id, []).extend(unsubs)

    async def _handle_event(self, evt_type: EventType, evt_data: dict | None) -> None:
        """Dispatch events with no branching duplication."""
        if not evt_data:
            return

        handler = self._dispatch.get(evt_type)
        if handler is None:
            return  # silently ignore unknown/unhandled types

        try:
            notify_type, item_id, cur_item = handler(evt_data)
        except Exception:  # pylint: disable=broad-exception-caught
            # defensive: a bug in a handler should not kill the loop
            self._logger.exception("Event handler failed for %s", evt_type)
            return

        if item_id is None or cur_item is None:
            return

        self._notify_subscribers(notify_type, item_id, cur_item)

    # --- Per-event helpers --------------------------------------------------

    def _evt_resource_added(
        self, data: dict
    ) -> tuple[EventType, str | None, Any | None]:
        item_id = self._id_of(data)
        if not item_id or self.item_cls is None:
            return _NOOP

        try:
            cur_item = self._items[item_id] = dataclass_from_dict(self.item_cls, data)  # type: ignore[arg-type]
        except (KeyError, ValueError, TypeError) as exc:
            self._logger.error(
                "Unable to parse resource, please report this to the authors of aioampio.",
                exc_info=exc,
            )
            return _NOOP

        self._subscribe_topics_for(
            item_id, data.get("owner", ""), data.get("states", [])
        )
        return (EventType.RESOURCE_ADDED, item_id, cur_item)

    def _evt_resource_deleted(
        self, data: dict
    ) -> tuple[EventType, str | None, Any | None]:
        item_id = self._id_of(data)
        if not item_id:
            return (EventType.RESOURCE_DELETED, None, None)

        # Best-effort unsubscribe and topic cleanup
        for unsub in self._unsubs.pop(item_id, []):
            with suppress(Exception):
                unsub()
        # Remove only topics owned by this item_id (O(k) for its topics)
        for t in [t for t, owner in self._topics.items() if owner == item_id]:
            self._topics.pop(t, None)

        # Return the last known resource object (if present) to subscribers
        cur_item = self._items.pop(item_id, None)
        return (EventType.RESOURCE_DELETED, item_id, cur_item)

    def _evt_resource_updated(
        self, data: dict
    ) -> tuple[EventType, str | None, Any | None]:
        item_id = self._id_of(data)
        if not item_id:
            return _NOOP
        cur_item = self._items.get(item_id)
        return (
            (EventType.RESOURCE_UPDATED, item_id, cur_item)
            if cur_item is not None
            else _NOOP
        )

    def _evt_entity_updated(
        self, data: dict
    ) -> tuple[EventType, str | None, Any | None]:
        topic = data.get("topic")
        if not topic:
            return _NOOP
        owner_id = self._topics.get(topic)
        if not owner_id:
            return _NOOP
        cur_item = self._items.get(owner_id)
        if cur_item is None:
            return _NOOP
        cur_item.update(topic, data.get("data", {}))
        return (EventType.RESOURCE_UPDATED, owner_id, cur_item)

    # --- Subscriber notify --------------------------------------------------

    def _notify_subscribers(
        self, evt_type: EventType, item_id: str, cur_item: AmpioResource | dict | None
    ) -> None:
        """Notify matching subscribers; safe against callback errors."""
        subs = list(self._subscribers.get(item_id, [])) + list(
            self._subscribers.get(ID_FILTER_ALL, [])
        )
        for callback, event_filter in subs:
            if event_filter is not None and evt_type not in event_filter:
                continue
            try:
                result = callback(evt_type, cur_item)
                if inspect.isawaitable(result):
                    asyncio.create_task(result)
            except Exception:  # pylint: disable=broad-exception-caught
                self._logger.exception("Subscriber callback failed for %s", item_id)

    # ---------------------------------------------------------------------
    # Internal Ampio API Commands
    # ---------------------------------------------------------------------

    async def _send_multiframe_command(self, id: str, payload: bytes) -> None:
        """Send a multiframe command using the controller CAN ID path."""
        device = self.get_device(id)
        if device is None:
            self._logger.error("Device not found for id: %s", id)
            return
        for p in generate_multican_payload(device.can_id, payload):
            await self._bridge.send(CTRL_CAN_ID, data=p)

    async def _send_command(self, id: str, payload: bytes) -> None:
        """Send a single-frame command using the controller CAN ID path."""
        device = self.get_device(id)
        if device is None:
            self._logger.error("Device not found for id: %s", id)
            return

        payload = struct.pack(">I", device.can_id) + payload
        await self._bridge.send(CTRL_CAN_ID, data=payload)

    def _get_entity_index_or_log(self, id: str) -> int | None:
        """Extract entity index from composite id and mask to 8 bits."""
        entity_index = get_entity_index(id)
        if entity_index is None:
            self._logger.error("Failed to extract switch number from id: %s", id)
            return None
        return entity_index & 0xFF
