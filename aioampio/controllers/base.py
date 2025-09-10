"""Base controller for managing Ampio entities."""

import asyncio
from collections.abc import Callable, Iterator
from inspect import iscoroutinefunction
import struct

from dataclasses import asdict
from types import NoneType
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
    item_cls: AmpioResource | None = None

    def __init__(self, bridge: "AmpioBridge") -> None:
        """Initialize the controller."""
        self._bridge = bridge
        self._items: dict[str, AmpioResource] = {}
        self._topics: dict[str, AmpioResource] = {}
        self._logger = bridge.logger.getChild(self.item_type.value)  # type: ignore  # noqa: PGH003
        self._subscribers: dict[str, EventSubscriptionType] = {ID_FILTER_ALL: []}
        self._initialized = False

    @property
    def items(self) -> list[AmpioResource]:
        """Return a list of all items."""
        return list(self._items.values())

    async def initialize(self) -> None:
        """Initialize the controller by loading existing resources."""
        resources = [x for x in self._bridge.config if x.type == self.item_type]

        for resource in resources:
            await self._handle_event(EventType.RESOURCE_ADDED, asdict(resource))

        item_type_str = (
            self.item_type.value if self.item_type is not None else "Unknown"
        )
        self._logger.info("Initialized %d %s", len(self._items), item_type_str)

        self._initialized = True

    def subscribe(
        self,
        callback: EventCallBackType,
        id_filter: str | tuple[str] | None = None,
        event_filter: EventType | tuple[EventType] | None = None,
    ) -> Callable:
        """Subscribe to status changes for this resource type."""
        if not isinstance(event_filter, NoneType | list | tuple):
            event_filter = (event_filter,)

        if id_filter is None:
            id_filter = (ID_FILTER_ALL,)
        elif not isinstance(id_filter, list | tuple):
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
            return self.get(id)
        item = self.get(id)
        owner = getattr(item, "owner", None)
        if not owner:
            return None
        return self._bridge.devices.get(owner)

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

    async def _handle_event(self, evt_type: EventType, evt_data: dict | None) -> None:
        """Handle an event from the bridge."""
        if evt_data is None:
            return

        item_id = evt_data.get("id")
        if evt_type == EventType.RESOURCE_ADDED:
            # print("RESOURCE_ADDED", evt_data)
            try:
                cur_item = self._items[item_id] = dataclass_from_dict(
                    self.item_cls,
                    evt_data,
                )
            except (KeyError, ValueError, TypeError) as exc:
                # In an attempt to not completely crash when a single resource can't be parsed
                # due to API schema mismatches, bugs in Hue or other factors, we allow some
                # resources to be skipped. This only works for resources that are not dependees
                # for other resources so we define this in the controller level.
                self._logger.error(
                    "Unable to parse resource, please report this to the authors of aioampio.",
                    exc_info=exc,
                )
                return
            for topic in evt_data.get("states", []):
                full_topic = f"{evt_data['owner']}.{topic}"
                self._topics[full_topic] = item_id
                self._bridge.entities.on_change(self._handle_event, topic=full_topic)

        elif evt_type == EventType.RESOURCE_DELETED:
            cur_item = self._items.pop(item_id, evt_data)

        elif evt_type == EventType.RESOURCE_UPDATED:
            cur_item = self._items.get(item_id)

        elif evt_type == EventType.ENTITY_UPDATED:
            # print("ENTITY_UPDATED", evt_data)
            topic = evt_data.get("topic")
            item_id = self._topics.get(topic)
            cur_item = self._items.get(item_id)
            cur_item.update(topic, evt_data.get("data", {}))
            await self._handle_event(EventType.RESOURCE_UPDATED, asdict(cur_item))
        else:
            # ignore other events
            return

        subscribers = (
            self._subscribers.get(item_id, []) + self._subscribers[ID_FILTER_ALL]
        )
        for callback, event_filter in subscribers:
            if event_filter is not None and evt_type not in event_filter:
                continue
            if iscoroutinefunction(callback):
                asyncio.create_task(callback(evt_type, cur_item))
            else:
                callback(evt_type, cur_item)

    # Internal Ampio API Commands
    async def _send_multiframe_command(self, id: str, payload: bytes) -> None:
        """Send a cover command payload twice."""
        device = self.get_device(id)
        if device is None:
            self._logger.error("Device not found for id: %s", id)
            return
        for _ in range(2):
            async with self._bridge.transport.client.atomic(CTRL_CAN_ID) as a:
                for p in generate_multican_payload(device.can_id, payload):
                    await a.send(p)

    async def _send_command(self, id: str, payload: bytes) -> None:
        """Send a command payload."""
        device = self.get_device(id)
        if device is None:
            self._logger.error("Device not found for id: %s", id)
            return

        payload = struct.pack(">I", device.can_id) + payload
        await self._bridge.transport.send(
            0x0F000000,
            data=payload,
        )

    def _get_entity_index_or_log(self, id: str) -> int | None:
        entity_index = get_entity_index(id)
        if entity_index is None:
            self._logger.error("Failed to extract switch number from id: %s", id)
            return None
        return entity_index & 0xFF
