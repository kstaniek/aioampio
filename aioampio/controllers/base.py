"""Base controller for managing Ampio entities."""

import asyncio
from collections.abc import Callable, Iterator
import inspect
import struct

from dataclasses import asdict
from typing import (
    Any,
    TYPE_CHECKING,
    TypeVar,
)

from dacite import from_dict as dataclass_from_dict

from aioampio.controllers.events import EventCallBackType, EventType
from aioampio.controllers.utils import generate_multican_payload, get_entity_index

from aioampio.models.device import Device

from aioampio.models.resource import ResourceTypes


if TYPE_CHECKING:
    from aioampio.bridge import AmpioBridge

EventSubscriptionType = tuple[EventCallBackType, tuple[EventType] | None]

ID_FILTER_ALL = "*"
CTRL_CAN_ID = 0x0F000000

AmpioResource = TypeVar("AmpioResource")


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
        self._logger = bridge.logger.getChild(self.item_type.value)  # type: ignore  # noqa: PGH003
        self._subscribers: dict[str, list[EventSubscriptionType]] = {ID_FILTER_ALL: []}
        self._initialized = False
        # item_id -> list[unsubscribe]
        self._unsubs: dict[str, list[Callable[[], None]]] = {}

        self._dispatch: dict[
            EventType, Callable[[dict], tuple[EventType, str | None, Any | None]]
        ] = {
            EventType.RESOURCE_ADDED: self._evt_resource_added,
            EventType.RESOURCE_DELETED: self._evt_resource_deleted,
            EventType.RESOURCE_UPDATED: self._evt_resource_updated,
            EventType.ENTITY_UPDATED: self._evt_entity_updated,  # normalized to RESOURCE_UPDATED
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
        id_filter: str | tuple[str] | None = None,
        event_filter: EventType | tuple[EventType] | None = None,
    ) -> Callable:
        """Subscribe to status changes for this resource type."""
        if event_filter is not None and not isinstance(event_filter, (list, tuple)):
            event_filter = (event_filter,)

        if id_filter is None:
            id_filter = (ID_FILTER_ALL,)
        elif id_filter is not None and not isinstance(id_filter, (list, tuple)):
            id_filter = (id_filter,)

        subscription = (callback, event_filter)
        for id_key in id_filter:
            self._subscribers.setdefault(id_key, []).append(subscription)

        def unsubscribe():
            for id_key in id_filter:
                if id_key not in self._subscribers:
                    continue
                self._subscribers[id_key].remove(subscription)

        return unsubscribe

    def get_device(self, id: str) -> Device | None:
        """Return the device associated with the given resource."""
        if self.item_type == ResourceTypes.DEVICE:
            item = self.get(id)
            return item if isinstance(item, Device) else None
        item = self.get(id)
        owner = getattr(item, "owner", None) if item is not None else None
        if not owner:
            return None
        dev = self._bridge.devices.get(owner)
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
        """RESOURCE_ADDED → build item, subscribe topics."""
        item_id = data.get("id")
        if not item_id:
            return (EventType.RESOURCE_ADDED, None, None)

        try:
            cur_item = self._items[item_id] = dataclass_from_dict(
                self.item_cls,  # type: ignore[arg-type]
                data,
            )
        except (KeyError, ValueError, TypeError) as exc:
            self._logger.error(
                "Unable to parse resource, please report this to the authors of aioampio.",
                exc_info=exc,
            )
            return (EventType.RESOURCE_ADDED, None, None)

        # topics → owner map + unsubscribe handles
        unsubs: list[Callable[[], None]] = []
        for topic in data.get("states", []):
            full_topic = f"{data['owner']}.{topic}"
            self._topics[full_topic] = item_id
            unsub = self._bridge.state_store.on_change(
                self._handle_event, topic=full_topic
            )
            unsubs.append(unsub)
        if unsubs:
            self._unsubs.setdefault(item_id, []).extend(unsubs)

        return (EventType.RESOURCE_ADDED, item_id, cur_item)

    def _evt_resource_deleted(
        self, data: dict
    ) -> tuple[EventType, str | None, Any | None]:
        """RESOURCE_DELETED → unsubscribe & drop item."""
        item_id = data.get("id")
        if not item_id:
            return (EventType.RESOURCE_DELETED, None, None)

        # unsubscribe
        for unsub in self._unsubs.pop(item_id, []):
            try:
                unsub()
            except Exception:  # pylint: disable=broad-exception-caught
                self._logger.exception("Error while unsubscribing for %s", item_id)

        # clear topic mappings
        for t, owner in list(self._topics.items()):
            if owner == item_id:
                self._topics.pop(t, None)

        cur_item = self._items.pop(item_id, data)
        return (EventType.RESOURCE_DELETED, item_id, cur_item)

    def _evt_resource_updated(
        self, data: dict
    ) -> tuple[EventType, str | None, Any | None]:
        """RESOURCE_UPDATED → pass through current item if present."""
        item_id = data.get("id")
        if not item_id:
            return (EventType.RESOURCE_UPDATED, None, None)
        cur_item = self._items.get(item_id)
        if cur_item is None:
            return (EventType.RESOURCE_UPDATED, None, None)
        return (EventType.RESOURCE_UPDATED, item_id, cur_item)

    def _evt_entity_updated(
        self, data: dict
    ) -> tuple[EventType, str | None, Any | None]:
        """ENTITY_UPDATED → apply to owning item; normalize as RESOURCE_UPDATED."""
        topic = data.get("topic")
        if not topic:
            return (EventType.RESOURCE_UPDATED, None, None)

        owner_id = self._topics.get(topic)
        if owner_id is None:
            return (EventType.RESOURCE_UPDATED, None, None)

        cur_item = self._items.get(owner_id)
        if cur_item is None:
            return (EventType.RESOURCE_UPDATED, None, None)

        # entity dataclasses expose .update(topic, data)
        cur_item.update(topic, data.get("data", {}))
        return (EventType.RESOURCE_UPDATED, owner_id, cur_item)

    # --- Subscriber notify --------------------------------------------------

    def _notify_subscribers(
        self, evt_type: EventType, item_id: str, cur_item: AmpioResource | dict | None
    ) -> None:
        """Notify matching subscribers; safe against callback errors."""
        # Copy lists so we’re safe if callbacks mutate subscriptions
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
        """Send a cover command payload twice."""
        device = self.get_device(id)
        if device is None:
            self._logger.error("Device not found for id: %s", id)
            return
        for p in generate_multican_payload(device.can_id, payload):
            await self._bridge.send(CTRL_CAN_ID, data=p)

    async def _send_command(self, id: str, payload: bytes) -> None:
        """Send a command payload."""
        device = self.get_device(id)
        if device is None:
            self._logger.error("Device not found for id: %s", id)
            return

        payload = struct.pack(">I", device.can_id) + payload
        await self._bridge.send(CTRL_CAN_ID, data=payload)

    def _get_entity_index_or_log(self, id: str) -> int | None:
        entity_index = get_entity_index(id)
        if entity_index is None:
            self._logger.error("Failed to extract switch number from id: %s", id)
            return None
        return entity_index & 0xFF
