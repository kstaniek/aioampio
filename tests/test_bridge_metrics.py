"""Tests for BridgeMetrics dataclass (Phase 2.4)."""

from aioampio.bridge import BridgeMetrics


class TestBridgeMetricsCreation:
    """Test BridgeMetrics instantiation."""

    def test_create_basic_metrics(self) -> None:
        """Test creating metrics with basic values."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="test-session-123",
            reconnects=2,
            connection_uptime_s=100.5,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=5,
            tx_errors=2,
            rx_rate_s=10.5,
            tx_rate_s=5.2,
            rx_queue_depth=50,
            last_rx_age_s=1.0,
            last_tx_age_s=2.0,
        )

        assert metrics.connected is True
        assert metrics.connection_state == "CONNECTED"
        assert metrics.session_id == "test-session-123"
        assert metrics.reconnects == 2
        assert metrics.connection_uptime_s == 100.5
        assert metrics.rx_total == 1000
        assert metrics.tx_total == 500

    def test_create_disconnected_metrics(self) -> None:
        """Test creating metrics for disconnected state."""
        metrics = BridgeMetrics(
            connected=False,
            connection_state="DISCONNECTED",
            session_id=None,
            reconnects=0,
            connection_uptime_s=None,
            rx_total=0,
            tx_total=0,
            rx_enqueued=0,
            rx_proc_queued=0,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=0.0,
            tx_rate_s=0.0,
            rx_queue_depth=0,
            last_rx_age_s=None,
            last_tx_age_s=None,
        )

        assert metrics.connected is False
        assert metrics.session_id is None
        assert metrics.connection_uptime_s is None


class TestBridgeMetricsHealthy:
    """Test BridgeMetrics.is_healthy property."""

    def test_healthy_when_connected_no_errors(self) -> None:
        """Test healthy state with no errors."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=100,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is True

    def test_unhealthy_when_disconnected(self) -> None:
        """Test unhealthy when disconnected."""
        metrics = BridgeMetrics(
            connected=False,
            connection_state="DISCONNECTED",
            session_id=None,
            reconnects=0,
            connection_uptime_s=None,
            rx_total=0,
            tx_total=0,
            rx_enqueued=0,
            rx_proc_queued=0,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=0.0,
            tx_rate_s=0.0,
            rx_queue_depth=0,
            last_rx_age_s=None,
            last_tx_age_s=None,
        )

        assert metrics.is_healthy is False

    def test_unhealthy_when_excessive_tx_errors(self) -> None:
        """Test unhealthy when TX errors exceed threshold."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=101,  # Over threshold of 100
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=100,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is False

    def test_healthy_at_tx_error_threshold(self) -> None:
        """Test healthy at exactly TX error threshold."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=100,  # At threshold
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=100,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is True

    def test_unhealthy_when_excessive_rx_drops(self) -> None:
        """Test unhealthy when RX drops exceed threshold."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=10000,
            tx_total=500,
            rx_enqueued=10000,
            rx_proc_queued=9000,
            rx_dropped=1001,  # Over threshold of 1000
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=100,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is False

    def test_healthy_at_rx_drop_threshold(self) -> None:
        """Test healthy at exactly RX drop threshold."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=10000,
            tx_total=500,
            rx_enqueued=10000,
            rx_proc_queued=9000,
            rx_dropped=1000,  # At threshold
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=100,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is True

    def test_unhealthy_when_queue_depth_high(self) -> None:
        """Test unhealthy when queue depth exceeds threshold."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=801,  # Over 80% of default 1000
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is False

    def test_healthy_at_queue_depth_threshold(self) -> None:
        """Test healthy at exactly queue depth threshold."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=800,  # At 80% threshold
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is True


class TestBridgeMetricsRecentActivity:
    """Test recent RX/TX activity properties."""

    def test_has_recent_rx_when_recent(self) -> None:
        """Test has_recent_rx when RX is recent."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=100,
            tx_total=50,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=10,
            last_rx_age_s=15.0,  # Less than 30 seconds
            last_tx_age_s=15.0,
        )

        assert metrics.has_recent_rx is True

    def test_no_recent_rx_when_old(self) -> None:
        """Test has_recent_rx when RX is old."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=100,
            tx_total=50,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=0.1,
            tx_rate_s=0.0,
            rx_queue_depth=10,
            last_rx_age_s=45.0,  # More than 30 seconds
            last_tx_age_s=None,
        )

        assert metrics.has_recent_rx is False

    def test_no_recent_rx_when_none(self) -> None:
        """Test has_recent_rx when no RX ever."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=10.0,
            rx_total=0,
            tx_total=0,
            rx_enqueued=0,
            rx_proc_queued=0,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=0.0,
            tx_rate_s=0.0,
            rx_queue_depth=0,
            last_rx_age_s=None,
            last_tx_age_s=None,
        )

        assert metrics.has_recent_rx is False

    def test_has_recent_rx_at_threshold(self) -> None:
        """Test has_recent_rx at exactly 30 second threshold."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=100,
            tx_total=50,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=1.0,
            tx_rate_s=0.5,
            rx_queue_depth=10,
            last_rx_age_s=30.0,  # Exactly 30 seconds
            last_tx_age_s=None,
        )

        assert metrics.has_recent_rx is False  # Threshold is <30, not <=30

    def test_has_recent_tx_when_recent(self) -> None:
        """Test has_recent_tx when TX is recent."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=100,
            tx_total=50,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=10,
            last_rx_age_s=5.0,
            last_tx_age_s=10.0,  # Less than 30 seconds
        )

        assert metrics.has_recent_tx is True

    def test_no_recent_tx_when_old(self) -> None:
        """Test has_recent_tx when TX is old."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=100,
            tx_total=50,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=5.0,
            tx_rate_s=0.1,
            rx_queue_depth=10,
            last_rx_age_s=5.0,
            last_tx_age_s=60.0,  # More than 30 seconds
        )

        assert metrics.has_recent_tx is False

    def test_no_recent_tx_when_none(self) -> None:
        """Test has_recent_tx when no TX ever."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=10.0,
            rx_total=100,
            tx_total=0,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=0.0,
            rx_queue_depth=10,
            last_rx_age_s=5.0,
            last_tx_age_s=None,
        )

        assert metrics.has_recent_tx is False


class TestBridgeMetricsErrorRate:
    """Test error_rate property."""

    def test_error_rate_with_no_tx(self) -> None:
        """Test error rate when no TX messages."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=10.0,
            rx_total=100,
            tx_total=0,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=5,  # Errors but no TX
            rx_rate_s=10.0,
            tx_rate_s=0.0,
            rx_queue_depth=10,
            last_rx_age_s=1.0,
            last_tx_age_s=None,
        )

        assert metrics.error_rate == 0.0

    def test_error_rate_with_no_errors(self) -> None:
        """Test error rate when no errors."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=10,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.error_rate == 0.0

    def test_error_rate_calculation(self) -> None:
        """Test error rate calculation."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=1000,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=50,  # 5% error rate
            rx_rate_s=10.0,
            tx_rate_s=10.0,
            rx_queue_depth=10,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.error_rate == 0.05

    def test_error_rate_all_errors(self) -> None:
        """Test error rate when all TX are errors."""
        metrics = BridgeMetrics(
            connected=False,
            connection_state="DISCONNECTED",
            session_id=None,
            reconnects=5,
            connection_uptime_s=None,
            rx_total=100,
            tx_total=100,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=100,  # 100% error rate
            rx_rate_s=0.0,
            tx_rate_s=0.0,
            rx_queue_depth=0,
            last_rx_age_s=None,
            last_tx_age_s=None,
        )

        assert metrics.error_rate == 1.0


class TestBridgeMetricsDropRate:
    """Test drop_rate property."""

    def test_drop_rate_with_no_enqueued(self) -> None:
        """Test drop rate when nothing enqueued."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=10.0,
            rx_total=0,
            tx_total=0,
            rx_enqueued=0,
            rx_proc_queued=0,
            rx_dropped=10,  # Drops but nothing enqueued
            tx_errors=0,
            rx_rate_s=0.0,
            tx_rate_s=0.0,
            rx_queue_depth=0,
            last_rx_age_s=None,
            last_tx_age_s=None,
        )

        assert metrics.drop_rate == 0.0

    def test_drop_rate_with_no_drops(self) -> None:
        """Test drop rate when no drops."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=1000,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=1000,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=10,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.drop_rate == 0.0

    def test_drop_rate_calculation(self) -> None:
        """Test drop rate calculation."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="session-1",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=950,
            tx_total=500,
            rx_enqueued=1000,
            rx_proc_queued=950,
            rx_dropped=50,  # 5% drop rate
            tx_errors=0,
            rx_rate_s=10.0,
            tx_rate_s=5.0,
            rx_queue_depth=10,
            last_rx_age_s=1.0,
            last_tx_age_s=1.0,
        )

        assert metrics.drop_rate == 0.05

    def test_drop_rate_all_dropped(self) -> None:
        """Test drop rate when all messages dropped."""
        metrics = BridgeMetrics(
            connected=False,
            connection_state="DISCONNECTED",
            session_id=None,
            reconnects=5,
            connection_uptime_s=None,
            rx_total=0,
            tx_total=0,
            rx_enqueued=1000,
            rx_proc_queued=0,
            rx_dropped=1000,  # 100% drop rate
            tx_errors=0,
            rx_rate_s=0.0,
            tx_rate_s=0.0,
            rx_queue_depth=0,
            last_rx_age_s=None,
            last_tx_age_s=None,
        )

        assert metrics.drop_rate == 1.0


class TestBridgeMetricsToDict:
    """Test to_dict() method."""

    def test_to_dict_complete(self) -> None:
        """Test to_dict() contains all fields."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="test-123",
            reconnects=3,
            connection_uptime_s=500.5,
            rx_total=10000,
            tx_total=5000,
            rx_enqueued=10000,
            rx_proc_queued=9950,
            rx_dropped=50,
            tx_errors=25,
            rx_rate_s=20.5,
            tx_rate_s=10.2,
            rx_queue_depth=150,
            last_rx_age_s=2.5,
            last_tx_age_s=3.5,
        )

        result = metrics.to_dict()

        assert result["connected"] is True
        assert result["connection_state"] == "CONNECTED"
        assert result["session_id"] == "test-123"
        assert result["reconnects"] == 3
        assert result["rx_total"] == 10000
        assert result["tx_total"] == 5000
        assert result["rx_rate_s"] == 20.5
        assert result["tx_rate_s"] == 10.2
        assert result["rx_enqueued"] == 10000
        assert result["rx_proc_queued"] == 9950
        assert result["rx_dropped"] == 50
        assert result["tx_errors"] == 25
        assert result["rx_queue_depth"] == 150
        assert result["last_rx_age_s"] == 2.5
        assert result["last_tx_age_s"] == 3.5
        assert result["connection_uptime_s"] == 500.5

    def test_to_dict_with_none_values(self) -> None:
        """Test to_dict() with None values."""
        metrics = BridgeMetrics(
            connected=False,
            connection_state="DISCONNECTED",
            session_id=None,
            reconnects=0,
            connection_uptime_s=None,
            rx_total=0,
            tx_total=0,
            rx_enqueued=0,
            rx_proc_queued=0,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=0.0,
            tx_rate_s=0.0,
            rx_queue_depth=0,
            last_rx_age_s=None,
            last_tx_age_s=None,
        )

        result = metrics.to_dict()

        assert result["session_id"] is None
        assert result["connection_uptime_s"] is None
        assert result["last_rx_age_s"] is None
        assert result["last_tx_age_s"] is None

    def test_to_dict_returns_typed_dict(self) -> None:
        """Test that to_dict() returns properly typed dictionary."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="test",
            reconnects=0,
            connection_uptime_s=100.0,
            rx_total=100,
            tx_total=50,
            rx_enqueued=100,
            rx_proc_queued=100,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=1.0,
            tx_rate_s=0.5,
            rx_queue_depth=10,
            last_rx_age_s=1.0,
            last_tx_age_s=2.0,
        )

        result = metrics.to_dict()

        # Check types
        assert isinstance(result["connected"], bool)
        assert isinstance(result["connection_state"], str)
        assert isinstance(result["reconnects"], int)
        assert isinstance(result["rx_total"], int)
        assert isinstance(result["tx_total"], int)
        assert isinstance(result["rx_rate_s"], float)
        assert isinstance(result["tx_rate_s"], float)


class TestBridgeMetricsScenarios:
    """Test realistic BridgeMetrics scenarios."""

    def test_initial_connection_metrics(self) -> None:
        """Test metrics for newly connected bridge."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="new-session",
            reconnects=0,
            connection_uptime_s=5.0,
            rx_total=10,
            tx_total=5,
            rx_enqueued=10,
            rx_proc_queued=10,
            rx_dropped=0,
            tx_errors=0,
            rx_rate_s=2.0,
            tx_rate_s=1.0,
            rx_queue_depth=0,
            last_rx_age_s=0.5,
            last_tx_age_s=1.0,
        )

        assert metrics.is_healthy is True
        assert metrics.has_recent_rx is True
        assert metrics.has_recent_tx is True
        assert metrics.error_rate == 0.0
        assert metrics.drop_rate == 0.0

    def test_heavily_loaded_metrics(self) -> None:
        """Test metrics for heavily loaded bridge."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="CONNECTED",
            session_id="busy-session",
            reconnects=0,
            connection_uptime_s=3600.0,
            rx_total=1000000,
            tx_total=500000,
            rx_enqueued=1000000,
            rx_proc_queued=999500,
            rx_dropped=500,
            tx_errors=100,
            rx_rate_s=277.7,  # ~1M per hour
            tx_rate_s=138.8,
            rx_queue_depth=700,
            last_rx_age_s=0.1,
            last_tx_age_s=0.1,
        )

        assert metrics.is_healthy is True  # Within thresholds
        assert metrics.error_rate == 0.0002  # 0.02%
        assert metrics.drop_rate == 0.0005  # 0.05%

    def test_degraded_connection_metrics(self) -> None:
        """Test metrics for degraded connection."""
        metrics = BridgeMetrics(
            connected=True,
            connection_state="RECONNECTING",
            session_id="degraded-session",
            reconnects=10,
            connection_uptime_s=50.0,
            rx_total=5000,
            tx_total=2000,
            rx_enqueued=6000,
            rx_proc_queued=5000,
            rx_dropped=1001,  # Over threshold
            tx_errors=50,
            rx_rate_s=5.0,
            tx_rate_s=2.0,
            rx_queue_depth=500,
            last_rx_age_s=10.0,
            last_tx_age_s=15.0,
        )

        assert metrics.is_healthy is False  # Too many drops
        assert metrics.drop_rate > 0.15  # >15% drops
