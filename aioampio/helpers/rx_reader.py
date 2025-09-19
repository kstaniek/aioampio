"""Asyncio CAN bus reader with backpressure."""

import asyncio
from typing import Callable

import can


class BoundedAsyncCanReader:
    """Thread-safe CAN -> asyncio.Queue bridge with backpressure."""

    def __init__(
        self,
        loop: asyncio.AbstractEventLoop,
        maxsize: int = 2000,
        drop_oldest: bool = True,
        on_drop: Callable[[], None] | None = None,
        on_enqueue: Callable[[], None] | None = None,
    ) -> None:
        self._loop = loop
        self._q: asyncio.Queue[can.Message] = asyncio.Queue(maxsize=maxsize)
        self._drop_oldest = drop_oldest
        self._on_drop = on_drop
        self._on_enqueue = on_enqueue

        class _Listener(can.Listener):
            def __init__(self, parent: "BoundedAsyncCanReader") -> None:
                self._p = parent

            def on_message_received(self, msg: can.Message) -> None:
                self._p._from_thread(msg)  # pylint: disable=protected-access

        self.listener = _Listener(self)

    def _from_thread(self, msg: can.Message) -> None:
        def enqueue() -> None:
            q = self._q
            if q.full():
                # backpressure policy
                if self._drop_oldest:
                    try:
                        q.get_nowait()  # drop oldest
                    except asyncio.QueueEmpty:
                        pass
                else:
                    if self._on_drop:
                        self._on_drop()
                    return  # drop newest
                if self._on_drop:
                    self._on_drop()
            try:
                q.put_nowait(msg)
                if self._on_enqueue:
                    self._on_enqueue()
            except asyncio.QueueFull:
                # Extremely unlikely after drop_oldest, account as drop
                if self._on_drop:
                    self._on_drop()

        # Notifier calls from a non-async thread
        self._loop.call_soon_threadsafe(enqueue)

    async def get(self) -> can.Message:
        """Get the next CAN message from the queue."""
        return await self._q.get()

    def qsize(self) -> int:
        """Get the current size of the queue."""
        return self._q.qsize()
