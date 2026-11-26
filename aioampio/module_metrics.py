"""Per-module traffic observed by this bridge, independent of consumers."""

from dataclasses import dataclass, replace
from datetime import UTC, datetime, timedelta
import time
from collections.abc import Iterable

import can


def received_timestamp(received_at: float) -> datetime:
    """Capture UTC reception time, accounting for reader callback scheduling delay."""
    return datetime.now(UTC) - timedelta(
        seconds=max(0.0, time.monotonic() - received_at)
    )


@dataclass(frozen=True, slots=True)
class ModuleMetrics:
    """Immutable traffic snapshot; counts reset only with the bridge instance.

    RX counts structurally valid frames from a configured module, even without
    a decoder or changed values. TX counts successful sends to that module, not
    acknowledgements or commands from other controllers. Ages use monotonic time.
    A missing RX age means no frame has arrived in the current connection session.
    """

    rx_total: int = 0
    tx_total: int = 0
    last_rx_age_s: float | None = None
    last_rx_at: datetime | None = None


class ModuleTraffic:
    """Track configured module IDs on the bridge event loop."""

    def __init__(self, can_ids: Iterable[int]) -> None:
        self._totals = dict.fromkeys(can_ids, ModuleMetrics())
        self._last_rx: dict[int, float] = {}

    def reset_session(self) -> None:
        """Require fresh RX after reconnect while preserving counters."""
        self._last_rx.clear()

    def receive(
        self, msg: can.Message, received_at: float, timestamp: datetime | None = None
    ) -> None:
        """Count one valid source frame before decoding and queue drops."""
        if msg.arbitration_id not in self._totals:
            return
        if (
            msg.is_error_frame
            or msg.is_remote_frame
            or not msg.is_extended_id
            or not msg.data
            or msg.dlc != len(msg.data)
        ):
            return
        can_id = msg.arbitration_id
        current = self._totals[can_id]
        self._totals[can_id] = replace(
            current,
            rx_total=current.rx_total + 1,
            last_rx_at=timestamp or received_timestamp(received_at),
        )
        self._last_rx[can_id] = received_at

    def transmit(self, msg: can.Message) -> None:
        """Count successful addressed Ampio frames, including each fragment."""
        if msg.arbitration_id != 0x0F000000 or len(msg.data) < 5:
            return
        can_id = int.from_bytes(msg.data[:4], "big")
        if can_id in self._totals:
            current = self._totals[can_id]
            self._totals[can_id] = replace(current, tx_total=current.tx_total + 1)

    def snapshot(self) -> dict[int, ModuleMetrics]:
        """Return detached snapshots without exposing mutable internal counters."""
        now = time.monotonic()
        return {
            can_id: replace(
                counts,
                last_rx_age_s=(
                    max(0.0, now - self._last_rx[can_id])
                    if can_id in self._last_rx
                    else None
                ),
            )
            for can_id, counts in self._totals.items()
        }
