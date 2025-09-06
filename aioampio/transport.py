"""Transport layer for Ampio communication."""

from __future__ import annotations
import asyncio
import logging
from collections.abc import Callable, Awaitable
from collections.abc import Sequence

from caneth import WaveShareCANClient, CANFrame


log = logging.getLogger(__name__)

FrameCallback = Callable[[CANFrame], Awaitable[None] | None]


class CanethTransport:
    """Transport layer for Caneth communication."""

    def __init__(self, host: str, port: int, name: str = "CAN1") -> None:
        self.client = WaveShareCANClient(host, port, name=name)
        self._rx_task: asyncio.Task | None = None
        self._callbacks: list[FrameCallback] = []
        # Optional selective RX filters: list of (can_id, d0, d1)
        self._filters: Sequence[tuple[int, int | None, int | None]] = []

    def set_filters(
        self, filters: Sequence[tuple[int, int | None, int | None]]
    ) -> None:
        """Install selective RX filters using caneth.register_callback.

        If provided, we will NOT install a global on_frame handler.
        Each filter is (can_id, d0, d1) where d0/d1 can be None (wildcard).
        """
        self._filters = filters or []

    def on_frame(self, callback: FrameCallback) -> None:
        """Register a callback to be called when a CAN frame is received."""
        self._callbacks.append(callback)

    async def start(self) -> None:
        """Start the transport layer."""
        if self._filters:
            for can_id, d0, d1 in self._filters:
                self.client.register_callback(can_id, d0, d1, self._dispatch)
        else:
            self.client.on_frame(self._dispatch)
        await self.client.start()
        await self.client.wait_connected(10)
        log.info("CAN transport connected: %s:%d", self.client.host, self.client.port)

    async def close(self) -> None:
        """Close the transport layer."""
        await self.client.close()
        if self._rx_task:
            self._rx_task.cancel()

    async def send(
        self,
        can_id: int,
        data: bytes | bytearray,
        *,
        extended: bool | None = None,
        rtr: bool = False,
    ) -> None:
        """Send a CAN frame."""
        if len(data) > 8:
            raise ValueError("CAN data length must be <= 8")
        await self.client.send(
            can_id, data, extended=extended, rtr=rtr, wait_for_space=True
        )

    async def _dispatch(self, frame: CANFrame) -> None:
        for cb in list(self._callbacks):
            try:
                res = cb(frame)
                if asyncio.iscoroutine(res):
                    await res
            except Exception as exc:  # pylint: disable=broad-except
                log.exception("Error in RX callback: %s", exc)
