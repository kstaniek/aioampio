"""Bridge configuration with validation.

This module provides the BridgeConfig dataclass which centralizes all
configuration options for the Ampio bridge. The configuration includes:

- Connection timeouts and retry behavior
- Watchdog timeouts for detecting connection issues
- Queue sizes for message buffering
- Error thresholds for triggering reconnection
- Worker pool sizing
- Metrics collection parameters

The configuration is validated at initialization to catch common
misconfiguration errors early. Validation checks include:
- Positive values for all timeouts
- Consistent watchdog timeout relationships
- Reasonable queue sizes
- Valid worker counts

Example:
    >>> config = BridgeConfig(
    ...     read_timeout_s=5.0,
    ...     reconnect_max_s=60.0,
    ...     rx_worker_count=2
    ... )
    >>> config.read_timeout_s
    5.0

Classes:
    BridgeConfig: Validated configuration dataclass

Raises:
    ValueError: If configuration validation fails
"""

from dataclasses import dataclass
import math
from typing import ClassVar


@dataclass
class BridgeConfig:
    """Bridge configuration with comprehensive validation.

    All timeout values are in seconds. Queue sizes are in number of messages.
    This dataclass uses __post_init__ to validate relationships between
    configuration values, ensuring the configuration is internally consistent.

    Attributes:
        read_timeout_s: Timeout for CAN message read operations
        reconnect_initial_s: Initial delay before first reconnection attempt
        reconnect_max_s: Maximum delay between reconnection attempts
        tx_timeout_s: Timeout for CAN message transmission
        idle_reconnect_s: Max idle time before forcing reconnect (None to disable)
        rx_gap_reconnect_s: Max gap between RX messages before reconnect (None to disable)
        max_no_rx_after_connect_s: Timeout for first RX after connect (None to disable)
        rx_queue_size: Size of the RX processing queue
        bounded_reader_size: Size of the bounded CAN reader buffer
        tx_error_reconnect_threshold: Consecutive TX errors before reconnect
        max_consecutive_rx_errors: Max consecutive RX errors per worker
        rx_worker_count: Number of concurrent RX worker tasks
        rate_smoothing_alpha: EMA smoothing factor for rate metrics (0..1)
        queue_full_log_interval: Log every N queue full events

    Raises:
        ValueError: If any validation check fails

    Example:
        >>> # Production configuration with conservative timeouts
        >>> config = BridgeConfig(
        ...     read_timeout_s=2.0,
        ...     reconnect_max_s=30.0,
        ...     idle_reconnect_s=60.0,
        ...     rx_worker_count=2
        ... )

        >>> # Testing configuration with aggressive timeouts
        >>> test_config = BridgeConfig(
        ...     read_timeout_s=0.5,
        ...     reconnect_max_s=5.0,
        ...     idle_reconnect_s=10.0,
        ...     rx_worker_count=1
        ... )
    """

    # Connection timeouts
    read_timeout_s: float = 2.0
    reconnect_initial_s: float = 0.5
    reconnect_max_s: float = 30.0
    tx_timeout_s: float = 1.0

    # Watchdog timeouts (None to disable)
    idle_reconnect_s: float | None = None
    rx_gap_reconnect_s: float | None = None
    max_no_rx_after_connect_s: float | None = None

    # Queue sizes
    rx_queue_size: int = 1000
    bounded_reader_size: int = 2000

    # Error thresholds
    tx_error_reconnect_threshold: int = 3
    max_consecutive_rx_errors: int = 10

    # Workers
    rx_worker_count: int = 1

    # Metrics
    rate_smoothing_alpha: float = 0.6  # EMA factor (0..1), higher = more reactive
    queue_full_log_interval: int = 100  # Log every N drops

    # Constants
    CTRL_CAN_ID: ClassVar[int] = 0x0F000000

    def __post_init__(self) -> None:  # pylint: disable=too-many-branches
        """Validate configuration relationships."""
        errors = []

        for name in (
            "read_timeout_s",
            "reconnect_initial_s",
            "reconnect_max_s",
            "tx_timeout_s",
        ):
            value = getattr(self, name)
            if not math.isfinite(value) or value <= 0:
                errors.append(f"{name} must be > 0 and finite, got {value}")
        for name in (
            "idle_reconnect_s",
            "rx_gap_reconnect_s",
            "max_no_rx_after_connect_s",
        ):
            value = getattr(self, name)
            if value is not None and (not math.isfinite(value) or value <= 0):
                errors.append(f"{name} must be > 0 and finite, or None, got {value}")

        # Validate reconnect relationship
        if self.reconnect_initial_s > self.reconnect_max_s:
            errors.append(
                f"reconnect_initial_s ({self.reconnect_initial_s}) must be <= "
                f"reconnect_max_s ({self.reconnect_max_s})"
            )

        # Validate watchdog timeout relationships
        if self.max_no_rx_after_connect_s and self.idle_reconnect_s:
            if self.max_no_rx_after_connect_s > self.idle_reconnect_s:
                errors.append(
                    f"max_no_rx_after_connect_s ({self.max_no_rx_after_connect_s}) "
                    f"should be <= idle_reconnect_s ({self.idle_reconnect_s})"
                )

        if self.rx_gap_reconnect_s and self.idle_reconnect_s:
            if self.rx_gap_reconnect_s > self.idle_reconnect_s:
                errors.append(
                    f"rx_gap_reconnect_s ({self.rx_gap_reconnect_s}) should be <= "
                    f"idle_reconnect_s ({self.idle_reconnect_s})"
                )

        # Validate queue sizes
        if self.rx_queue_size <= 0:
            errors.append(f"rx_queue_size must be > 0, got {self.rx_queue_size}")

        if self.bounded_reader_size <= 0:
            errors.append(
                f"bounded_reader_size must be > 0, got {self.bounded_reader_size}"
            )

        # Validate thresholds
        if self.tx_error_reconnect_threshold <= 0:
            errors.append(
                f"tx_error_reconnect_threshold must be > 0, "
                f"got {self.tx_error_reconnect_threshold}"
            )

        if self.max_consecutive_rx_errors <= 0:
            errors.append(
                f"max_consecutive_rx_errors must be > 0, "
                f"got {self.max_consecutive_rx_errors}"
            )

        # Validate worker count
        if self.rx_worker_count <= 0:
            errors.append(f"rx_worker_count must be > 0, got {self.rx_worker_count}")

        # Validate rate smoothing alpha
        if not 0.0 < self.rate_smoothing_alpha <= 1.0:
            errors.append(
                f"rate_smoothing_alpha must be in (0, 1], "
                f"got {self.rate_smoothing_alpha}"
            )

        # Validate log interval
        if self.queue_full_log_interval <= 0:
            errors.append(
                f"queue_full_log_interval must be > 0, "
                f"got {self.queue_full_log_interval}"
            )

        if errors:
            raise ValueError(
                "Bridge configuration validation failed:\n  - " + "\n  - ".join(errors)
            )
