"""Bridge metrics types and health assessment."""

from dataclasses import dataclass
from typing import TypedDict


class BridgeMetricsDict(TypedDict):
    """Type definition for bridge metrics dictionary.

    This TypedDict provides type safety for the metrics returned by
    the bridge's metrics property.
    """

    connected: bool
    connection_state: str
    session_id: str | None
    reconnects: int
    rx_total: int
    tx_total: int
    rx_rate_s: float
    tx_rate_s: float
    rx_enqueued: int
    rx_proc_queued: int
    rx_dropped: int
    tx_errors: int
    rx_queue_depth: int
    last_rx_age_s: float | None
    last_tx_age_s: float | None
    connection_uptime_s: float | None


@dataclass
class BridgeMetrics:  # pylint: disable=too-many-instance-attributes
    """Bridge metrics with health assessment.

    Provides structured access to bridge metrics and health indicators.
    """

    # Connection metrics
    connected: bool
    connection_state: str
    session_id: str | None
    reconnects: int
    connection_uptime_s: float | None

    # Message counters
    rx_total: int
    tx_total: int
    rx_enqueued: int
    rx_proc_queued: int

    # Error/drop counters
    rx_dropped: int
    tx_errors: int

    # Rates (messages per second)
    rx_rate_s: float
    tx_rate_s: float

    # Queue metrics
    rx_queue_depth: int

    # Timing metrics
    last_rx_age_s: float | None
    last_tx_age_s: float | None

    @property
    def is_healthy(self) -> bool:
        """Check if bridge is in healthy state.

        Returns:
            True if bridge is healthy
        """
        if not self.connected:
            return False

        # Check for excessive errors
        if self.tx_errors > 100:
            return False

        # Check for excessive drops
        if self.rx_dropped > 1000:
            return False

        # Check for queue backlog (using 80% threshold)
        # Note: Queue size is configuration-dependent
        if self.rx_queue_depth > 800:  # Assumes default 1000 queue size
            return False

        return True

    @property
    def has_recent_rx(self) -> bool:
        """Check if RX activity is recent.

        Returns:
            True if received message in last 30 seconds
        """
        if self.last_rx_age_s is None:
            return False
        return self.last_rx_age_s < 30.0

    @property
    def has_recent_tx(self) -> bool:
        """Check if TX activity is recent.

        Returns:
            True if transmitted message in last 30 seconds
        """
        if self.last_tx_age_s is None:
            return False
        return self.last_tx_age_s < 30.0

    @property
    def error_rate(self) -> float:
        """Calculate TX error rate.

        Returns:
            Ratio of errors to total TX (0.0 to 1.0), or 0.0 if no TX
        """
        if self.tx_total == 0:
            return 0.0
        return self.tx_errors / self.tx_total

    @property
    def drop_rate(self) -> float:
        """Calculate RX drop rate.

        Returns:
            Ratio of drops to total enqueued (0.0 to 1.0), or 0.0 if none enqueued
        """
        if self.rx_enqueued == 0:
            return 0.0
        return self.rx_dropped / self.rx_enqueued

    def to_dict(self) -> BridgeMetricsDict:
        """Convert to dictionary format.

        Returns:
            Dictionary with all metrics
        """
        return {
            "connected": self.connected,
            "connection_state": self.connection_state,
            "session_id": self.session_id,
            "reconnects": self.reconnects,
            "rx_total": self.rx_total,
            "tx_total": self.tx_total,
            "rx_rate_s": self.rx_rate_s,
            "tx_rate_s": self.tx_rate_s,
            "rx_enqueued": self.rx_enqueued,
            "rx_proc_queued": self.rx_proc_queued,
            "rx_dropped": self.rx_dropped,
            "tx_errors": self.tx_errors,
            "rx_queue_depth": self.rx_queue_depth,
            "last_rx_age_s": self.last_rx_age_s,
            "last_tx_age_s": self.last_tx_age_s,
            "connection_uptime_s": self.connection_uptime_s,
        }
