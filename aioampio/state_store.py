"""State store for Ampio topics with change notifications."""

from __future__ import annotations

import asyncio
import inspect
import math
from typing import Any, TYPE_CHECKING, Awaitable, Callable

from .codec.base import AmpioMessage
from .controllers.events import EventType

if TYPE_CHECKING:
    from aioampio.bridge import AmpioBridge

ChangeCallback = Callable[[EventType, dict | None], Awaitable[None] | None]


class StateStore:
    """Stores latest payload per topic and notifies subscribers of changes.

    - Key: `topic` (str)
    - Value: arbitrary JSON-like payload
    - Callbacks fire only when the payload actually changes
    - Notification order is preserved per topic
    """

    def __init__(self, bridge: AmpioBridge) -> None:
        """Initialize the state store."""
        self._bridge = bridge
        self._values: dict[str, Any] = {}
        self._callbacks: list[ChangeCallback] = []
        self._callbacks_by_topic: dict[str, list[ChangeCallback]] = {}
        self._lock = asyncio.Lock()

    def get(self, topic: str) -> Any | None:
        """Get the latest payload for a topic, or None if not set."""
        return self._values.get(topic)

    def snapshot(self) -> dict[str, Any]:
        """Get a snapshot of all stored values."""
        return dict(self._values)

    def on_change(
        self, cb: ChangeCallback, *, topic: str | None = None
    ) -> Callable[[], None]:
        """Register a callback to be called when an entity changes."""
        if topic is None:
            lst = self._callbacks
        else:
            lst = self._callbacks_by_topic.setdefault(topic, [])
        if cb not in lst:
            lst.append(cb)

        def unsubscribe() -> None:
            if cb in self._callbacks:
                self._callbacks.remove(cb)
            if topic is not None:
                lst_t = self._callbacks_by_topic.get(topic)
                if lst_t and cb in lst_t:
                    lst_t.remove(cb)
                    if not lst_t:
                        self._callbacks_by_topic.pop(topic, None)

        return unsubscribe

    async def apply_message(self, msg: AmpioMessage) -> bool:
        """Apply an incoming AmpioMessage to update the state store."""
        return await self.set(msg.topic, msg.payload)

    async def set(self, topic: str, payload: Any) -> bool:
        """Set the payload for a topic, notifying subscribers if it changed."""
        async with self._lock:
            old = self._values.get(topic)
            if self._equal(old, payload):
                return False
            self._values[topic] = payload
        await self._notify(topic, payload, old)
        return True

    async def _notify(self, topic: str, new: Any, old: Any | None) -> None:
        """Notify subscribers of a change to a topic."""
        msg = {"topic": topic, "data": new, "previous": old}
        for cb in list(self._callbacks) + list(self._callbacks_by_topic.get(topic, [])):
            try:
                res = cb(EventType.ENTITY_UPDATED, msg)
                if inspect.isawaitable(res):
                    await res
            except asyncio.CancelledError:  # pylint: disable=try-except-raise
                raise
            except Exception:  # pylint: disable=broad-except
                self._bridge.logger.exception(
                    "Entity callback failed for topic %s", topic
                )

    @staticmethod
    def _equal(a: Any, b: Any) -> bool:
        """Check if two values are equal, handling special cases."""
        if a is b:
            return True
        if isinstance(a, (bytes, bytearray)) and isinstance(b, (bytes, bytearray)):
            return bytes(a) == bytes(b)
        if isinstance(a, float) and isinstance(b, float):
            if math.isnan(a) and math.isnan(b):
                return True
        try:
            return bool(a == b)
        except Exception:  # pylint: disable=broad-except
            return False
