"""Reusable metrics mixin for controllers."""

from __future__ import annotations
from typing import Any


class ControllerMetrics:
    """Reusable metrics mixin for controllers.

    Assumes the concrete controller exposes:
      - self._items: dict[str, Any]
      - self._topics: dict[str, str]
    """

    __slots__ = (
        "_events_dispatched_total",
        "_updates_applied_total",
        "_send_attempts_total",
        "_metrics_extra",
    )

    def __init__(self) -> None:
        """Initialize the metrics."""
        self._events_dispatched_total: int = 0
        self._updates_applied_total: int = 0
        self._send_attempts_total: int = 0
        # Optional extension point for controller-specific extras
        self._metrics_extra: dict[str, Any] = {}

    # ---- hooks you call from the controller at key points ----
    def _metrics_inc_event_dispatched(self) -> None:
        """Call when an event is dispatched to subscribers."""
        self._events_dispatched_total += 1

    def _metrics_inc_update_applied(self) -> None:
        """Call when an update is applied."""
        self._updates_applied_total += 1

    def _metrics_inc_send_attempt(self, n: int = 1) -> None:
        """Call when a send attempt is made."""
        self._send_attempts_total += int(n)

    # ---- derived / exposed metrics ----
    # derived gauges
    @property
    def items_count(self) -> int:
        """Return current count of managed items."""
        items = getattr(self, "_items", None)
        return len(items) if items is not None else 0

    @property
    def topics_count(self) -> int:
        """Return current count of managed topics."""
        topics = getattr(self, "_topics", None)
        return len(topics) if topics is not None else 0

    @property
    def controller_metrics(self) -> dict[str, Any]:
        """Return current controller metrics."""
        return {
            "items_count": self.items_count,
            "topics_count": self.topics_count,
            "events_dispatched_total": self._events_dispatched_total,
            "updates_applied_total": self._updates_applied_total,
            "send_attempts_total": self._send_attempts_total,
            **self._metrics_extra,
        }

    def metrics_set(self, key: str, value: Any) -> None:
        """Set an extra metric (extension point)."""
        self._metrics_extra[key] = value
