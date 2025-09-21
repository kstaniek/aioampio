# tests/test_controller_base.py
from __future__ import annotations

import asyncio
import inspect
import logging
from dataclasses import dataclass, field
from typing import Callable, Tuple

import pytest

from aioampio.controllers.base import AmpioResourceController, ID_FILTER_ALL
from aioampio.controllers.events import EventType
from aioampio.models.resource import ResourceTypes


# --- Ensure a main-thread loop exists for this module -------------------------


@pytest.fixture(autouse=True, scope="module")
def _ensure_main_loop():
    """Install a default event loop on MainThread for synchronous tests."""
    try:
        asyncio.get_running_loop()
        # A loop is already running (unlikely for these sync tests).
        yield
        return
    except RuntimeError:
        pass

    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    try:
        yield
    finally:
        try:
            loop.close()
        finally:
            asyncio.set_event_loop(None)


# --------------------------
# Test doubles / scaffolding
# --------------------------


class _DummyStateStore:
    """Minimal state store that records on_change callbacks and can emit them."""

    def __init__(self) -> None:
        self._subs: dict[str, list[Callable]] = {}

    def on_change(self, cb: Callable, *, topic: str):
        self._subs.setdefault(topic, []).append(cb)

        def unsub():
            lst = self._subs.get(topic, [])
            try:
                lst.remove(cb)
            except ValueError:
                pass
            if not lst:
                self._subs.pop(topic, None)

        return unsub

    def emit(self, topic: str, data: dict):
        """Simulate an incoming topic update by invoking callbacks.

        If a callback returns an awaitable (e.g., controller._handle_event),
        run it to completion so assertions can run immediately.
        """
        for cb in list(self._subs.get(topic, [])):
            res = cb(EventType.ENTITY_UPDATED, {"topic": topic, "data": data})
            if inspect.isawaitable(res):
                loop = asyncio.get_event_loop()
                if loop.is_running():
                    # We're already inside a running loop: schedule and wait cooperatively
                    # (this branch is unlikely in these sync tests).
                    task = loop.create_task(res)
                    # Let the task run to completion:
                    loop.run_until_complete(asyncio.sleep(0))
                    while not task.done():
                        loop.run_until_complete(asyncio.sleep(0))
                else:
                    loop.run_until_complete(res)


class _DummyDevices:
    def get(self, owner: str | None):
        return None


class _DummyBridge:
    def __init__(self) -> None:
        self.logger = logging.getLogger("test.controller")
        self.state_store = _DummyStateStore()
        self.devices = _DummyDevices()


@dataclass
class DummyItem:
    id: str
    owner: str
    states: list[str] = field(default_factory=list)
    updates: list[Tuple[str, dict]] = field(default_factory=list)

    def update(self, topic: str, data: dict) -> None:
        self.updates.append((topic, data))


class DummyController(AmpioResourceController[DummyItem]):
    item_type = ResourceTypes.TEXT
    item_cls = DummyItem


@pytest.fixture()
def ctrl() -> DummyController:
    return DummyController(_DummyBridge())


def _collecting_subscriber(bucket: list):
    def _cb(evt_type, item):
        bucket.append((evt_type, item))

    return _cb


def test_resource_added_subscribes_and_notifies(ctrl: DummyController):
    events: list = []
    ctrl.subscribe(_collecting_subscriber(events), id_filter=ID_FILTER_ALL)

    data = {"id": "dev1_itemA", "owner": "dev1", "states": ["s1", "s2"]}

    loop = asyncio.get_event_loop()
    loop.run_until_complete(ctrl._handle_event(EventType.RESOURCE_ADDED, data))

    assert "dev1_itemA" in ctrl
    item = ctrl["dev1_itemA"]
    assert item.owner == "dev1"
    assert ctrl._topics.get("dev1.s1") == "dev1_itemA"
    assert ctrl._topics.get("dev1.s2") == "dev1_itemA"
    assert events and events[-1][0] == EventType.RESOURCE_ADDED
    assert events[-1][1] is item


def test_entity_update_routes_to_owner_and_normalizes(ctrl: DummyController):
    events: list = []
    ctrl.subscribe(_collecting_subscriber(events), id_filter=ID_FILTER_ALL)

    data = {"id": "dev1_itemA", "owner": "dev1", "states": ["s1", "s2"]}
    loop = asyncio.get_event_loop()
    loop.run_until_complete(ctrl._handle_event(EventType.RESOURCE_ADDED, data))
    item = ctrl["dev1_itemA"]

    ctrl._bridge.state_store.emit("dev1.s1", {"x": 1})

    assert item.updates == [("dev1.s1", {"x": 1})]
    assert any(evt == EventType.RESOURCE_UPDATED for evt, _ in events)


def test_resource_deleted_cleans_up_and_notifies(ctrl: DummyController):
    events: list = []
    ctrl.subscribe(_collecting_subscriber(events), id_filter=ID_FILTER_ALL)

    data = {"id": "dev1_itemA", "owner": "dev1", "states": ["s1", "s2"]}
    loop = asyncio.get_event_loop()
    loop.run_until_complete(ctrl._handle_event(EventType.RESOURCE_ADDED, data))
    item_before = ctrl["dev1_itemA"]

    loop.run_until_complete(
        ctrl._handle_event(EventType.RESOURCE_DELETED, {"id": "dev1_itemA"})
    )

    assert "dev1_itemA" not in ctrl
    assert "dev1.s1" not in ctrl._topics
    assert "dev1.s2" not in ctrl._topics
    last_evt, last_item = events[-1]
    assert last_evt == EventType.RESOURCE_DELETED
    assert last_item is item_before

    # No further updates after deletion
    ctrl._bridge.state_store.emit("dev1.s1", {"x": 2})
    assert item_before.updates == []


def test_event_filtering(ctrl: DummyController):
    updated: list = []
    added: list = []

    ctrl.subscribe(_collecting_subscriber(added), event_filter=EventType.RESOURCE_ADDED)
    ctrl.subscribe(
        _collecting_subscriber(updated), event_filter=(EventType.RESOURCE_UPDATED,)
    )

    loop = asyncio.get_event_loop()
    loop.run_until_complete(
        ctrl._handle_event(
            EventType.RESOURCE_ADDED, {"id": "i1", "owner": "dev1", "states": []}
        )
    )
    assert added and added[-1][0] == EventType.RESOURCE_ADDED
    assert not updated

    loop.run_until_complete(
        ctrl._handle_event(EventType.RESOURCE_UPDATED, {"id": "i1"})
    )
    assert updated and updated[-1][0] == EventType.RESOURCE_UPDATED


def test_unknown_event_is_ignored(ctrl: DummyController):
    """Passing a non-dispatched key should be a no-op (no exception, no notify)."""
    events: list = []
    ctrl.subscribe(_collecting_subscriber(events), id_filter=ID_FILTER_ALL)

    # Use an object that won't be found in ctrl._dispatch keys
    unknown_event_key = object()

    loop = asyncio.get_event_loop()
    loop.run_until_complete(ctrl._handle_event(unknown_event_key, {"id": "x"}))  # type: ignore[arg-type]
    assert events == []
