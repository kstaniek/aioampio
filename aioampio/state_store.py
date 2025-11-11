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

    Thread Safety:
        - Reading/writing values is protected by an async lock
        - Notifications happen outside the lock to prevent blocking
        - Multiple notifications for different topics can run concurrently

    Callback Behavior:
        - Global callbacks receive notifications for all topics
        - Topic-specific callbacks only receive notifications for their topic
        - Global callbacks are notified before topic-specific ones
        - Callbacks are invoked with a snapshot of the callback list
        - Failed callbacks are logged but don't stop other notifications
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
        """Register a callback to be called when an entity changes.

        Args:
            cb: Callback function to invoke on changes. Can be sync or async.
               Receives (EventType, dict) where dict contains:
               - 'topic': The changed topic
               - 'data': The new payload value
               - 'previous': The old payload value (or None)
            topic: If provided, only receive notifications for this specific topic.
                   If None, receive notifications for all topics.

        Returns:
            Unsubscribe function that removes the callback when called

        Note:
            The same callback can be registered multiple times for different topics.
            If registered both globally and for a specific topic, it will be called
            twice for that topic's changes (once as global, once as topic-specific).
        """
        if topic is None:
            lst = self._callbacks
        else:
            lst = self._callbacks_by_topic.setdefault(topic, [])
        if cb not in lst:
            lst.append(cb)

        def unsubscribe() -> None:
            if topic is None:
                if cb in self._callbacks:
                    self._callbacks.remove(cb)
            else:
                lst_t = self._callbacks_by_topic.get(topic)
                if lst_t and cb in lst_t:
                    lst_t.remove(cb)
                    if not lst_t:
                        self._callbacks_by_topic.pop(topic, None)

        return unsubscribe

    async def apply_message(self, msg: AmpioMessage) -> bool:
        """Apply an incoming AmpioMessage to update the state store.

        Args:
            msg: Ampio message containing topic and payload

        Returns:
            True if the value changed and callbacks were notified, False if unchanged
        """
        return await self.set(msg.topic, msg.payload)

    async def set(self, topic: str, payload: Any) -> bool:
        """Set the payload for a topic, notifying subscribers if it changed.

        Args:
            topic: Topic identifier
            payload: New value for the topic (any JSON-serializable type)

        Returns:
            True if the value changed and callbacks were notified, False if unchanged
        """
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
