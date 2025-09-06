"""Entity Manager for managing Ampio entities."""

from __future__ import annotations

import asyncio
from typing import Any, TYPE_CHECKING
from collections.abc import Awaitable, Callable

from .codec.base import AmpioMessage
from .controllers.events import EventType

if TYPE_CHECKING:
    from aioampio.bridge import AmpioBridge

ChangeCallback = Callable[[EventType, dict | None], Awaitable[None] | None]


class EntityManager:
    """Stores latest payload per topic and notifies subscribers of changes.

    - Key: `topic` (str)
    - Value: arbitrary JSON-like payload (Ant)
    - Callbacks fire only when the payload actually changes
    """

    def __init__(self, bridge: AmpioBridge) -> None:
        self._bridge = bridge
        self._values: dict[str, Any] = {}
        self._callbacks: list[ChangeCallback] = []
        self._callbacks_by_topic: dict[str, list[ChangeCallback]] = {}
        self._lock = asyncio.Lock()

    def get(self, topic: str) -> Any | None:
        return self._values.get(topic)

    def snapshot(self) -> dict[str, Any]:
        return dict(self._values)

    def on_change(self, cb: ChangeCallback, *, topic: str | None = None) -> None:
        """Register a callback to be called when an entity changes.

        If `topic` is provided, the callback will only be called for changes to that topic.
        """
        if topic is None:
            self._callbacks.append(cb)
        else:
            self._callbacks_by_topic.setdefault(topic, []).append(cb)

    async def apply_message(self, msg: AmpioMessage) -> bool:
        """Store the latest payload for a topic and notify subscribers of changes.

        Returns True if the value changed, False otherwise.
        """
        return await self.set(msg.topic, msg.payload)

    async def set(self, topic: str, payload: Any) -> bool:
        async with self._lock:
            old = self._values.get(topic)
            if self._equal(old, payload):
                return False
            self._values[topic] = payload
        # fire the callback outside the lock
        await self._notify(topic, payload, old)
        return True

    async def _notify(self, topic: str, new: Any, old: Any | None) -> None:
        # global
        msg = {
            "topic": topic,
            "data": new,
            "previous": old,
        }
        for cb in list(self._callbacks):
            res = cb(EventType.ENTITY_UPDATED, msg)
            if asyncio.iscoroutine(res):
                await res
        # cb per topic
        for cb in self._callbacks_by_topic.get(topic, []):
            res = cb(EventType.ENTITY_UPDATED, msg)
            if asyncio.iscoroutine(res):
                await res

    @staticmethod
    def _equal(a: Any, b: Any) -> bool:
        """Check if two values are equal."""
        try:
            return bool(a == b)
        except Exception:
            return str(a) == str(b)
