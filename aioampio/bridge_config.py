"""Bridge configuration with validation."""

from dataclasses import dataclass
from typing import ClassVar


@dataclass
class BridgeConfig:
    """Bridge configuration with validation.

    All timeouts are in seconds. Queue sizes are in number of messages.
    """

    # Connection timeouts
    read_timeout_s: float = 2.0
    reconnect_initial_s: float = 0.5
    reconnect_max_s: float = 30.0
    tx_timeout_s: float = 1.0

    # Watchdog timeouts (None to disable)
    idle_reconnect_s: float | None = 60.0
    rx_gap_reconnect_s: float | None = 10.0
    max_no_rx_after_connect_s: float | None = 10.0

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

        # Validate timeouts are positive
        if self.read_timeout_s <= 0:
            errors.append(f"read_timeout_s must be > 0, got {self.read_timeout_s}")

        if self.reconnect_initial_s <= 0:
            errors.append(
                f"reconnect_initial_s must be > 0, got {self.reconnect_initial_s}"
            )

        if self.reconnect_max_s <= 0:
            errors.append(f"reconnect_max_s must be > 0, got {self.reconnect_max_s}")

        if self.tx_timeout_s <= 0:
            errors.append(f"tx_timeout_s must be > 0, got {self.tx_timeout_s}")

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
