"""TX (transmit) message handling for the Ampio bridge.

This module contains the TX (transmit) logic for sending CAN messages.
It handles message transmission, error tracking, and automatic reconnection
triggers based on error thresholds.

The TX handler provides:
- Thread-safe message transmission with async/await support
- Automatic reconnection on persistent transmission failures
- Error streak tracking to detect communication issues
- Proper locking to prevent race conditions during reconnection

Classes:
    TxHandler: Handles CAN message transmission with error recovery
"""

import asyncio
import logging
from typing import Callable

import can


class TxHandler:
    """Handles transmission of CAN messages with error recovery.

    The TX handler manages sending messages to the CAN bus while tracking
    errors and triggering reconnection when necessary. It uses a lock to
    ensure thread-safe access to the bus during transmission and reconnection.

    Attributes:
        logger: Logger for TX messages
        bus_lock: Lock protecting bus access during TX/reconnection
        reconnect_event: Event to trigger reconnection
        tx_timeout_s: Timeout for transmission operations (seconds)
        tx_error_threshold: Number of consecutive errors before reconnect
    """

    def __init__(
        self,
        logger: logging.Logger,
        bus_lock: asyncio.Lock,
        reconnect_event: asyncio.Event,
        tx_timeout_s: float,
        tx_error_threshold: int,
        on_tx_success: Callable[[], None] | None = None,
        on_tx_error: Callable[[Exception], None] | None = None,
    ) -> None:
        """Initialize TX handler.

        Args:
            logger: Logger for TX messages
            bus_lock: Lock protecting bus access
            reconnect_event: Event to set on persistent errors
            tx_timeout_s: Timeout for send operations (seconds)
            tx_error_threshold: Consecutive errors before triggering reconnect
            on_tx_success: Optional callback called on successful transmission
            on_tx_error: Optional callback called on transmission error
        """
        self.logger = logger
        self._bus_lock = bus_lock
        self._reconnect_event = reconnect_event
        self._tx_timeout_s = tx_timeout_s
        self._tx_error_threshold = tx_error_threshold
        self._on_tx_success = on_tx_success
        self._on_tx_error = on_tx_error
        self._tx_error_streak = 0

    async def send(
        self, bus: can.BusABC | None, can_id: int, data: bytes | memoryview
    ) -> bool:
        """Send a CAN message.

        Args:
            bus: CAN bus to send on (None if disconnected)
            can_id: CAN arbitration ID (29-bit extended)
            data: Frame payload (max 8 bytes for CAN 2.0)

        Returns:
            True if message was sent successfully, False otherwise

        Note:
            Messages are dropped silently if bus is None or reconnecting.
            Errors are logged and may trigger reconnection.
        """
        # Fast path: early exit without lock if reconnecting
        if self._reconnect_event.is_set():
            self.logger.debug("TX dropped; reconnect pending")
            return False

        # Lock-protected bus access to prevent TOCTOU race condition
        async with self._bus_lock:
            if bus is None:
                self.logger.debug("TX dropped; bus not connected")
                return False

            msg = can.Message(
                arbitration_id=can_id,
                data=bytes(data),
                is_extended_id=True,
                is_fd=False,
            )
            loop = asyncio.get_running_loop()
            try:
                await loop.run_in_executor(None, bus.send, msg, self._tx_timeout_s)
                self._tx_error_streak = 0  # Reset on success
                self.logger.debug("TX id=0x%X len=%d", can_id, len(msg.data))
                if self._on_tx_success:
                    self._on_tx_success()
                return True
            except can.CanError as e:
                self._handle_error(can_id, e)
                return False
            except OSError as e:
                # Network/device errors (e.g., device unplugged)
                self._handle_error(can_id, e)
                return False

    def _handle_error(self, can_id: int, error: Exception) -> None:
        """Handle transmission error with reconnect logic.

        Args:
            can_id: The CAN ID that failed to send
            error: The exception that occurred
        """
        self._tx_error_streak += 1
        self.logger.error("TX failed; dropping frame id=0x%X: %s", can_id, error)

        if self._on_tx_error:
            self._on_tx_error(error)

        # Trigger reconnect if error threshold exceeded or bus is closed
        if (
            "closed" in str(error).lower()
            or self._tx_error_streak >= self._tx_error_threshold
        ):
            self.logger.warning(
                "TX error threshold reached (%d consecutive failures); triggering reconnect",
                self._tx_error_streak,
            )
            self._reconnect_event.set()

    def reset_error_streak(self) -> None:
        """Reset the consecutive error counter.

        This is typically called when a new connection is established.
        """
        self._tx_error_streak = 0

    @property
    def error_streak(self) -> int:
        """Get the current consecutive error count.

        Returns:
            Number of consecutive transmission errors
        """
        return self._tx_error_streak
