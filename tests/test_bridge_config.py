"""Tests for BridgeConfig dataclass (Phase 2.2)."""

import pytest

from aioampio.bridge import BridgeConfig


class TestBridgeConfigDefaults:
    """Test BridgeConfig default values."""

    def test_default_config_creation(self) -> None:
        """Test creating config with defaults."""
        config = BridgeConfig()

        # Connection timeouts
        assert config.read_timeout_s == 2.0
        assert config.reconnect_initial_s == 0.5
        assert config.reconnect_max_s == 30.0
        assert config.tx_timeout_s == 1.0

        # Watchdog timeouts
        assert config.idle_reconnect_s == 60.0
        assert config.rx_gap_reconnect_s == 10.0
        assert config.max_no_rx_after_connect_s == 10.0

        # Queue sizes
        assert config.rx_queue_size == 1000
        assert config.bounded_reader_size == 2000

        # Error thresholds
        assert config.tx_error_reconnect_threshold == 3
        assert config.max_consecutive_rx_errors == 10

        # Workers
        assert config.rx_worker_count == 1

        # Metrics
        assert config.rate_smoothing_alpha == 0.6
        assert config.queue_full_log_interval == 100

    def test_default_config_valid(self) -> None:
        """Test that default config passes validation."""
        # Should not raise any exceptions
        config = BridgeConfig()
        assert config is not None


class TestBridgeConfigCustomValues:
    """Test BridgeConfig with custom values."""

    def test_custom_timeouts(self) -> None:
        """Test creating config with custom timeout values."""
        config = BridgeConfig(
            read_timeout_s=5.0,
            reconnect_initial_s=1.0,
            reconnect_max_s=60.0,
            tx_timeout_s=2.0,
        )

        assert config.read_timeout_s == 5.0
        assert config.reconnect_initial_s == 1.0
        assert config.reconnect_max_s == 60.0
        assert config.tx_timeout_s == 2.0

    def test_custom_watchdog_timeouts(self) -> None:
        """Test creating config with custom watchdog timeouts."""
        config = BridgeConfig(
            idle_reconnect_s=120.0,
            rx_gap_reconnect_s=20.0,
            max_no_rx_after_connect_s=15.0,
        )

        assert config.idle_reconnect_s == 120.0
        assert config.rx_gap_reconnect_s == 20.0
        assert config.max_no_rx_after_connect_s == 15.0

    def test_disable_watchdogs(self) -> None:
        """Test disabling watchdogs via config."""
        config = BridgeConfig(
            idle_reconnect_s=None,
            rx_gap_reconnect_s=None,
            max_no_rx_after_connect_s=None,
        )

        assert config.idle_reconnect_s is None
        assert config.rx_gap_reconnect_s is None
        assert config.max_no_rx_after_connect_s is None

    def test_custom_queue_sizes(self) -> None:
        """Test creating config with custom queue sizes."""
        config = BridgeConfig(rx_queue_size=500, bounded_reader_size=1000)

        assert config.rx_queue_size == 500
        assert config.bounded_reader_size == 1000

    def test_custom_error_thresholds(self) -> None:
        """Test creating config with custom error thresholds."""
        config = BridgeConfig(
            tx_error_reconnect_threshold=5, max_consecutive_rx_errors=20
        )

        assert config.tx_error_reconnect_threshold == 5
        assert config.max_consecutive_rx_errors == 20

    def test_custom_worker_count(self) -> None:
        """Test creating config with custom worker count."""
        config = BridgeConfig(rx_worker_count=4)

        assert config.rx_worker_count == 4

    def test_custom_metrics(self) -> None:
        """Test creating config with custom metrics settings."""
        config = BridgeConfig(rate_smoothing_alpha=0.8, queue_full_log_interval=50)

        assert config.rate_smoothing_alpha == 0.8
        assert config.queue_full_log_interval == 50


class TestBridgeConfigValidation:
    """Test BridgeConfig validation rules."""

    def test_negative_read_timeout(self) -> None:
        """Test that negative read_timeout_s is rejected."""
        with pytest.raises(ValueError, match="read_timeout_s must be > 0"):
            BridgeConfig(read_timeout_s=-1.0)

    def test_zero_read_timeout(self) -> None:
        """Test that zero read_timeout_s is rejected."""
        with pytest.raises(ValueError, match="read_timeout_s must be > 0"):
            BridgeConfig(read_timeout_s=0.0)

    def test_negative_reconnect_initial(self) -> None:
        """Test that negative reconnect_initial_s is rejected."""
        with pytest.raises(ValueError, match="reconnect_initial_s must be > 0"):
            BridgeConfig(reconnect_initial_s=-1.0)

    def test_zero_reconnect_initial(self) -> None:
        """Test that zero reconnect_initial_s is rejected."""
        with pytest.raises(ValueError, match="reconnect_initial_s must be > 0"):
            BridgeConfig(reconnect_initial_s=0.0)

    def test_negative_reconnect_max(self) -> None:
        """Test that negative reconnect_max_s is rejected."""
        with pytest.raises(ValueError, match="reconnect_max_s must be > 0"):
            BridgeConfig(reconnect_max_s=-1.0)

    def test_zero_reconnect_max(self) -> None:
        """Test that zero reconnect_max_s is rejected."""
        with pytest.raises(ValueError, match="reconnect_max_s must be > 0"):
            BridgeConfig(reconnect_max_s=0.0)

    def test_negative_tx_timeout(self) -> None:
        """Test that negative tx_timeout_s is rejected."""
        with pytest.raises(ValueError, match="tx_timeout_s must be > 0"):
            BridgeConfig(tx_timeout_s=-1.0)

    def test_zero_tx_timeout(self) -> None:
        """Test that zero tx_timeout_s is rejected."""
        with pytest.raises(ValueError, match="tx_timeout_s must be > 0"):
            BridgeConfig(tx_timeout_s=0.0)

    def test_reconnect_initial_greater_than_max(self) -> None:
        """Test that reconnect_initial_s must be <= reconnect_max_s."""
        with pytest.raises(
            ValueError, match="reconnect_initial_s.*must be <=.*reconnect_max_s"
        ):
            BridgeConfig(reconnect_initial_s=60.0, reconnect_max_s=30.0)

    def test_reconnect_initial_equal_to_max(self) -> None:
        """Test that reconnect_initial_s can equal reconnect_max_s."""
        config = BridgeConfig(reconnect_initial_s=30.0, reconnect_max_s=30.0)
        assert config.reconnect_initial_s == config.reconnect_max_s

    def test_max_no_rx_greater_than_idle(self) -> None:
        """Test that max_no_rx_after_connect_s should be <= idle_reconnect_s."""
        with pytest.raises(
            ValueError,
            match="max_no_rx_after_connect_s.*should be <=.*idle_reconnect_s",
        ):
            BridgeConfig(max_no_rx_after_connect_s=100.0, idle_reconnect_s=50.0)

    def test_rx_gap_greater_than_idle(self) -> None:
        """Test that rx_gap_reconnect_s should be <= idle_reconnect_s."""
        with pytest.raises(
            ValueError, match="rx_gap_reconnect_s.*should be <=.*idle_reconnect_s"
        ):
            BridgeConfig(rx_gap_reconnect_s=100.0, idle_reconnect_s=50.0)

    def test_watchdog_relationships_with_none(self) -> None:
        """Test that watchdog validation skips None values."""
        # Should not raise even though the comparison would fail if both were numbers
        config = BridgeConfig(max_no_rx_after_connect_s=None, idle_reconnect_s=10.0)
        assert config is not None

        config = BridgeConfig(rx_gap_reconnect_s=None, idle_reconnect_s=10.0)
        assert config is not None

    def test_negative_rx_queue_size(self) -> None:
        """Test that negative rx_queue_size is rejected."""
        with pytest.raises(ValueError, match="rx_queue_size must be > 0"):
            BridgeConfig(rx_queue_size=-1)

    def test_zero_rx_queue_size(self) -> None:
        """Test that zero rx_queue_size is rejected."""
        with pytest.raises(ValueError, match="rx_queue_size must be > 0"):
            BridgeConfig(rx_queue_size=0)

    def test_negative_bounded_reader_size(self) -> None:
        """Test that negative bounded_reader_size is rejected."""
        with pytest.raises(ValueError, match="bounded_reader_size must be > 0"):
            BridgeConfig(bounded_reader_size=-1)

    def test_zero_bounded_reader_size(self) -> None:
        """Test that zero bounded_reader_size is rejected."""
        with pytest.raises(ValueError, match="bounded_reader_size must be > 0"):
            BridgeConfig(bounded_reader_size=0)

    def test_negative_tx_error_threshold(self) -> None:
        """Test that negative tx_error_reconnect_threshold is rejected."""
        with pytest.raises(
            ValueError, match="tx_error_reconnect_threshold must be > 0"
        ):
            BridgeConfig(tx_error_reconnect_threshold=-1)

    def test_zero_tx_error_threshold(self) -> None:
        """Test that zero tx_error_reconnect_threshold is rejected."""
        with pytest.raises(
            ValueError, match="tx_error_reconnect_threshold must be > 0"
        ):
            BridgeConfig(tx_error_reconnect_threshold=0)

    def test_negative_max_consecutive_rx_errors(self) -> None:
        """Test that negative max_consecutive_rx_errors is rejected."""
        with pytest.raises(ValueError, match="max_consecutive_rx_errors must be > 0"):
            BridgeConfig(max_consecutive_rx_errors=-1)

    def test_zero_max_consecutive_rx_errors(self) -> None:
        """Test that zero max_consecutive_rx_errors is rejected."""
        with pytest.raises(ValueError, match="max_consecutive_rx_errors must be > 0"):
            BridgeConfig(max_consecutive_rx_errors=0)

    def test_negative_rx_worker_count(self) -> None:
        """Test that negative rx_worker_count is rejected."""
        with pytest.raises(ValueError, match="rx_worker_count must be > 0"):
            BridgeConfig(rx_worker_count=-1)

    def test_zero_rx_worker_count(self) -> None:
        """Test that zero rx_worker_count is rejected."""
        with pytest.raises(ValueError, match="rx_worker_count must be > 0"):
            BridgeConfig(rx_worker_count=0)

    def test_rate_smoothing_alpha_zero(self) -> None:
        """Test that rate_smoothing_alpha = 0 is rejected."""
        with pytest.raises(
            ValueError, match="rate_smoothing_alpha must be in \\(0, 1\\]"
        ):
            BridgeConfig(rate_smoothing_alpha=0.0)

    def test_rate_smoothing_alpha_negative(self) -> None:
        """Test that negative rate_smoothing_alpha is rejected."""
        with pytest.raises(
            ValueError, match="rate_smoothing_alpha must be in \\(0, 1\\]"
        ):
            BridgeConfig(rate_smoothing_alpha=-0.1)

    def test_rate_smoothing_alpha_greater_than_one(self) -> None:
        """Test that rate_smoothing_alpha > 1 is rejected."""
        with pytest.raises(
            ValueError, match="rate_smoothing_alpha must be in \\(0, 1\\]"
        ):
            BridgeConfig(rate_smoothing_alpha=1.1)

    def test_rate_smoothing_alpha_exactly_one(self) -> None:
        """Test that rate_smoothing_alpha = 1.0 is valid."""
        config = BridgeConfig(rate_smoothing_alpha=1.0)
        assert config.rate_smoothing_alpha == 1.0

    def test_rate_smoothing_alpha_small_positive(self) -> None:
        """Test that small positive rate_smoothing_alpha is valid."""
        config = BridgeConfig(rate_smoothing_alpha=0.001)
        assert config.rate_smoothing_alpha == 0.001

    def test_negative_queue_full_log_interval(self) -> None:
        """Test that negative queue_full_log_interval is rejected."""
        with pytest.raises(ValueError, match="queue_full_log_interval must be > 0"):
            BridgeConfig(queue_full_log_interval=-1)

    def test_zero_queue_full_log_interval(self) -> None:
        """Test that zero queue_full_log_interval is rejected."""
        with pytest.raises(ValueError, match="queue_full_log_interval must be > 0"):
            BridgeConfig(queue_full_log_interval=0)

    def test_multiple_validation_errors(self) -> None:
        """Test that multiple validation errors are reported together."""
        with pytest.raises(ValueError) as exc_info:
            BridgeConfig(
                read_timeout_s=0.0,
                reconnect_initial_s=0.0,
                rx_queue_size=0,
            )

        error_message = str(exc_info.value)
        assert "read_timeout_s must be > 0" in error_message
        assert "reconnect_initial_s must be > 0" in error_message
        assert "rx_queue_size must be > 0" in error_message


class TestBridgeConfigEdgeCases:
    """Test BridgeConfig edge cases and corner scenarios."""

    def test_very_small_positive_timeouts(self) -> None:
        """Test that very small positive values are accepted."""
        config = BridgeConfig(
            read_timeout_s=0.001,
            reconnect_initial_s=0.001,
            reconnect_max_s=0.002,
            tx_timeout_s=0.001,
        )

        assert config.read_timeout_s == 0.001
        assert config.reconnect_initial_s == 0.001
        assert config.reconnect_max_s == 0.002

    def test_very_large_timeouts(self) -> None:
        """Test that very large timeout values are accepted."""
        config = BridgeConfig(
            read_timeout_s=1000.0,
            reconnect_initial_s=500.0,
            reconnect_max_s=2000.0,
        )

        assert config.read_timeout_s == 1000.0
        assert config.reconnect_initial_s == 500.0
        assert config.reconnect_max_s == 2000.0

    def test_minimum_queue_sizes(self) -> None:
        """Test minimum valid queue sizes."""
        config = BridgeConfig(rx_queue_size=1, bounded_reader_size=1)
        assert config.rx_queue_size == 1
        assert config.bounded_reader_size == 1

    def test_large_queue_sizes(self) -> None:
        """Test large queue sizes."""
        config = BridgeConfig(rx_queue_size=100000, bounded_reader_size=200000)
        assert config.rx_queue_size == 100000
        assert config.bounded_reader_size == 200000

    def test_single_error_threshold(self) -> None:
        """Test minimum error thresholds."""
        config = BridgeConfig(
            tx_error_reconnect_threshold=1, max_consecutive_rx_errors=1
        )
        assert config.tx_error_reconnect_threshold == 1
        assert config.max_consecutive_rx_errors == 1

    def test_many_workers(self) -> None:
        """Test large number of workers."""
        config = BridgeConfig(rx_worker_count=100)
        assert config.rx_worker_count == 100


class TestBridgeConfigScenarios:
    """Test realistic BridgeConfig scenarios."""

    def test_fast_reconnect_config(self) -> None:
        """Test configuration for fast reconnection."""
        config = BridgeConfig(
            reconnect_initial_s=0.1,
            reconnect_max_s=5.0,
        )

        assert config.reconnect_initial_s == 0.1
        assert config.reconnect_max_s == 5.0

    def test_conservative_timeout_config(self) -> None:
        """Test configuration with conservative timeouts."""
        config = BridgeConfig(
            idle_reconnect_s=300.0,
            rx_gap_reconnect_s=120.0,
            max_no_rx_after_connect_s=60.0,
        )

        assert config.idle_reconnect_s == 300.0
        assert config.rx_gap_reconnect_s == 120.0
        assert config.max_no_rx_after_connect_s == 60.0

    def test_aggressive_timeout_config(self) -> None:
        """Test configuration with aggressive timeouts."""
        config = BridgeConfig(
            idle_reconnect_s=10.0,
            rx_gap_reconnect_s=5.0,
            max_no_rx_after_connect_s=3.0,
        )

        assert config.idle_reconnect_s == 10.0
        assert config.rx_gap_reconnect_s == 5.0
        assert config.max_no_rx_after_connect_s == 3.0

    def test_testing_config(self) -> None:
        """Test configuration suitable for unit tests."""
        config = BridgeConfig(
            read_timeout_s=0.1,
            reconnect_initial_s=0.05,
            reconnect_max_s=1.0,
            tx_timeout_s=0.1,
            idle_reconnect_s=1.0,
            rx_gap_reconnect_s=0.5,
            max_no_rx_after_connect_s=0.3,
        )

        # All timeouts are small for fast tests
        assert config.read_timeout_s < 1.0
        assert config.idle_reconnect_s is not None and config.idle_reconnect_s <= 1.0
        assert config.rx_gap_reconnect_s is not None and config.rx_gap_reconnect_s < 1.0

    def test_no_watchdogs_config(self) -> None:
        """Test configuration with all watchdogs disabled."""
        config = BridgeConfig(
            idle_reconnect_s=None,
            rx_gap_reconnect_s=None,
            max_no_rx_after_connect_s=None,
        )

        assert config.idle_reconnect_s is None
        assert config.rx_gap_reconnect_s is None
        assert config.max_no_rx_after_connect_s is None

    def test_high_performance_config(self) -> None:
        """Test configuration for high performance."""
        config = BridgeConfig(
            rx_queue_size=10000,
            bounded_reader_size=20000,
            rx_worker_count=8,
            rate_smoothing_alpha=0.9,  # More reactive
        )

        assert config.rx_queue_size == 10000
        assert config.bounded_reader_size == 20000
        assert config.rx_worker_count == 8
        assert config.rate_smoothing_alpha == 0.9
