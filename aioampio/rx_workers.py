"""RX message processing workers for the Ampio bridge.

This module contains the RX (receive) worker logic that processes incoming
CAN messages from the processing queue. Workers run concurrently to handle
message decoding and state updates.

The worker pattern provides:
- Concurrent message processing for better throughput
- Error isolation (one worker failure doesn't stop others)
- Automatic error recovery with consecutive error tracking
- Clean shutdown on cancellation

Classes:
    RxWorkerManager: Manages a pool of RX worker tasks
"""

import asyncio
from contextlib import suppress
import logging
import time
from typing import Any, Callable, Awaitable

import can

from aioampio.codec.base import CANFrame
from aioampio.codec.registry import registry

_MAX_BATCH_SIZE = 16
_TIME_SLICE_S = 0.01


class RxWorkerManager:
    """Manages RX worker tasks for processing incoming CAN messages.

    The manager creates a pool of concurrent workers that pull messages from
    a processing queue and handle decoding and state updates. Each worker
    tracks consecutive errors and will stop if errors exceed a threshold.

    Attributes:
        logger: Logger for worker messages
        proc_queue: Queue containing CAN messages to process
        stop_event: Event signaling workers should stop
        on_frame: Async callback to process decoded messages
        on_message_processed: Optional callback when RX message is processed
        max_consecutive_errors: Maximum errors before worker stops (default: 10)
    """

    def __init__(
        self,
        logger: logging.Logger,
        proc_queue: asyncio.Queue[can.Message],
        stop_event: asyncio.Event,
        on_frame: Callable[[can.Message], Awaitable[None]],
        on_message_processed: Callable[[], None] | None = None,
        max_consecutive_errors: int = 10,
        on_worker_failed: Callable[[], None] | None = None,
    ) -> None:
        """Initialize RX worker manager.

        Args:
            logger: Logger for worker messages
            proc_queue: Queue containing CAN messages to process
            stop_event: Event signaling workers should stop
            on_frame: Async callback to process decoded messages
            on_message_processed: Optional callback when RX message is processed
            max_consecutive_errors: Maximum consecutive errors before worker stops
            on_worker_failed: Request session recovery after the error limit
        """
        self.logger = logger
        self._proc_queue = proc_queue
        self._stop_event = stop_event
        self._on_frame = on_frame
        self._on_message_processed = on_message_processed
        self._max_consecutive_errors = max_consecutive_errors
        self._on_worker_failed = on_worker_failed
        self._workers: list[asyncio.Task] = []

    async def _worker(self, idx: int) -> None:
        """Worker coroutine that processes messages from the queue.

        Args:
            idx: Worker index for logging
        """
        self.logger.debug("RX worker %d started", idx)
        consecutive_errors = 0
        batch_size = 0
        batch_started = time.monotonic()

        while not self._stop_event.is_set():
            try:
                msg = await self._proc_queue.get()
            except asyncio.CancelledError:
                self.logger.debug("RX worker %d cancelled", idx)
                break

            try:
                if self._on_message_processed:
                    self._on_message_processed()
                await self._on_frame(msg)
                consecutive_errors = 0  # Reset on success
            except Exception as e:  # pylint: disable=broad-exception-caught
                # Re-raise cancellation to properly shutdown
                if isinstance(e, asyncio.CancelledError):
                    raise
                consecutive_errors += 1
                self.logger.exception(
                    "RX worker %d processing failed (%d consecutive): %s",
                    idx,
                    consecutive_errors,
                    e,
                )

                if consecutive_errors >= self._max_consecutive_errors:
                    self.logger.critical(
                        "RX worker %d: too many consecutive errors (%d); stopping worker",
                        idx,
                        consecutive_errors,
                    )
                    if self._on_worker_failed:
                        self._on_worker_failed()
                    break

            batch_size += 1
            if (
                batch_size >= _MAX_BATCH_SIZE
                or time.monotonic() - batch_started >= _TIME_SLICE_S
            ):
                # A queued get and an async frame handler need not suspend.
                await asyncio.sleep(0)
                batch_size = 0
                batch_started = time.monotonic()

        self.logger.debug("RX worker %d stopped", idx)

    def start(self, n: int = 1) -> None:
        """Start RX worker pool.

        Args:
            n: Number of workers to start
        """
        self._workers = [asyncio.create_task(self._worker(i)) for i in range(n)]
        self.logger.info("Started %d RX worker(s)", n)

    async def stop(self) -> None:
        """Stop all RX workers and wait for them to finish."""
        for t in self._workers:
            t.cancel()
        for t in self._workers:
            with suppress(asyncio.CancelledError):
                await t
        self._workers.clear()

    @property
    def is_running(self) -> bool:
        """Check if any workers are running.

        Returns:
            True if at least one worker is running
        """
        return any(not t.done() for t in self._workers)

    @property
    def worker_count(self) -> int:
        """Get the number of workers.

        Returns:
            Number of worker tasks
        """
        return len(self._workers)


class FrameProcessor:
    """Processes CAN frames by decoding and validating them.

    This class handles the low-level frame validation and decoding logic,
    separating concerns from the worker management.

    Attributes:
        logger: Logger for processing messages
        on_decoded_message: Callback for each decoded message
    """

    def __init__(
        self,
        logger: logging.Logger,
        on_decoded_message: Callable[[Any], Awaitable[None]],
    ) -> None:
        """Initialize frame processor.

        Args:
            logger: Logger for processing messages
            on_decoded_message: Async callback for each decoded message
        """
        self.logger = logger
        self._on_decoded_message = on_decoded_message

    async def process(self, msg: can.Message) -> None:  # pylint: disable=too-many-return-statements
        """Process incoming CAN frame.

        Validates the frame, decodes it using registered codecs, and
        dispatches decoded messages to the callback.

        Args:
            msg: CAN message to process
        """
        # Validate frame format
        if msg.is_error_frame:
            self.logger.debug("Ignoring CAN error frame: %s", msg)
            return
        if not msg.is_extended_id:
            self.logger.debug("Ignoring non-extended CAN frame: %s", msg)
            return
        if msg.is_remote_frame:
            self.logger.debug("Ignoring remote CAN frame: %s", msg)
            return
        if msg.dlc != len(msg.data):
            self.logger.warning("Ignoring CAN frame with invalid DLC: %s", msg)
            return
        if not msg.data:
            self.logger.debug("Ignoring empty CAN frame: %s", msg)
            return

        # Create frame and decode
        frame = CANFrame(can_id=msg.arbitration_id, data=memoryview(msg.data))
        try:
            msgs = registry().decode(frame)
        except ValueError as e:
            # Invalid frame data format
            self.logger.warning("Invalid frame data id=0x%X: %s", msg.arbitration_id, e)
            return
        except KeyError as e:
            # No decoder registered for this frame type
            self.logger.debug("No decoder for frame id=0x%X: %s", msg.arbitration_id, e)
            return
        except Exception as e:  # pylint: disable=broad-exception-caught
            # Unexpected decoder error - log with full context
            self.logger.exception(
                "Decoder failed for frame id=0x%X: %s", msg.arbitration_id, e
            )
            return

        # Dispatch decoded messages
        if not msgs:
            return
        for m in msgs:
            await self._on_decoded_message(m)
