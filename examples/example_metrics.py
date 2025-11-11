"""Example demonstrating structured metrics functionality."""
# pylint: disable=protected-access,import-outside-toplevel,broad-exception-caught

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

from aioampio import AmpioBridge
from aioampio.bridge_config import BridgeConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


async def example_basic_metrics() -> None:
    """Example showing basic metrics access."""
    print("\n" + "=" * 60)
    print("Example 1: Basic Metrics Access")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    bridge = AmpioBridge(cfg, interface="virtual", channel="vcan0")
    await bridge.initialize()

    # Get structured metrics
    metrics = bridge.metrics

    print("\nConnection Status:")
    print(f"  Connected: {metrics.connected}")
    print(f"  State: {metrics.connection_state}")
    print(f"  Session ID: {metrics.session_id}")
    print(f"  Uptime: {metrics.connection_uptime_s}s")

    print("\nMessage Counters:")
    print(f"  RX Total: {metrics.rx_total}")
    print(f"  TX Total: {metrics.tx_total}")
    print(f"  RX Enqueued: {metrics.rx_enqueued}")
    print(f"  RX Processed: {metrics.rx_proc_queued}")

    print("\nError/Drop Counters:")
    print(f"  RX Dropped: {metrics.rx_dropped}")
    print(f"  TX Errors: {metrics.tx_errors}")

    print("\nRates:")
    print(f"  RX Rate: {metrics.rx_rate_s:.2f} msg/s")
    print(f"  TX Rate: {metrics.tx_rate_s:.2f} msg/s")

    print("\nQueue Status:")
    print(f"  Queue Depth: {metrics.rx_queue_depth}")


async def example_health_checks() -> None:
    """Example showing health assessment."""
    print("\n" + "=" * 60)
    print("Example 2: Health Assessment")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    bridge = AmpioBridge(cfg, interface="virtual", channel="vcan0")
    await bridge.initialize()

    metrics = bridge.metrics

    print("\nHealth Status:")
    print(f"  Overall Healthy: {metrics.is_healthy}")
    print(f"  Recent RX Activity: {metrics.has_recent_rx}")
    print(f"  Recent TX Activity: {metrics.has_recent_tx}")

    print("\nHealth Metrics:")
    print(f"  Error Rate: {metrics.error_rate:.2%}")
    print(f"  Drop Rate: {metrics.drop_rate:.2%}")

    print("\nActivity Timing:")
    print(f"  Last RX Age: {metrics.last_rx_age_s}s")
    print(f"  Last TX Age: {metrics.last_tx_age_s}s")


async def example_metrics_dict() -> None:
    """Example showing dictionary conversion."""
    print("\n" + "=" * 60)
    print("Example 3: Dictionary Conversion")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    bridge = AmpioBridge(cfg, interface="virtual", channel="vcan0")
    await bridge.initialize()

    # Get metrics as dataclass
    metrics = bridge.metrics
    print(f"\nMetrics object type: {type(metrics).__name__}")

    # Convert to dictionary
    metrics_dict = metrics.to_dict()
    print(f"Dictionary type: {type(metrics_dict).__name__}")

    # Or use backward-compatible method
    metrics_dict2 = bridge.get_metrics_dict()
    print(f"Backward-compatible method type: {type(metrics_dict2).__name__}")

    print("\nDictionary keys:")
    for key in sorted(metrics_dict.keys()):
        print(f"  - {key}")

    print("\nSample values:")
    print(f"  connected: {metrics_dict['connected']}")
    print(f"  connection_state: {metrics_dict['connection_state']}")
    print(f"  rx_total: {metrics_dict['rx_total']}")
    print(f"  tx_total: {metrics_dict['tx_total']}")


async def example_health_monitoring() -> None:
    """Example showing continuous health monitoring."""
    print("\n" + "=" * 60)
    print("Example 4: Health Monitoring Loop")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    bridge = AmpioBridge(cfg, interface="virtual", channel="vcan0")
    await bridge.initialize()

    print("\nMonitoring bridge health (3 iterations)...")

    for i in range(3):
        metrics = bridge.metrics

        status = "✓ HEALTHY" if metrics.is_healthy else "✗ UNHEALTHY"
        print(f"\nIteration {i + 1}: {status}")
        print(f"  State: {metrics.connection_state}")
        print(f"  RX: {metrics.rx_total} msgs ({metrics.rx_rate_s:.2f}/s)")
        print(f"  TX: {metrics.tx_total} msgs ({metrics.tx_rate_s:.2f}/s)")
        print(f"  Errors: {metrics.tx_errors}")
        print(f"  Drops: {metrics.rx_dropped}")
        print(
            f"  Queue: {metrics.rx_queue_depth}/{bridge._bridge_config.rx_queue_size}"
        )

        # Health indicators
        indicators = []
        if metrics.has_recent_rx:
            indicators.append("RX Active")
        if metrics.has_recent_tx:
            indicators.append("TX Active")
        if metrics.error_rate > 0:
            indicators.append(f"Error Rate: {metrics.error_rate:.1%}")
        if metrics.drop_rate > 0:
            indicators.append(f"Drop Rate: {metrics.drop_rate:.1%}")

        if indicators:
            print(f"  Indicators: {', '.join(indicators)}")

        await asyncio.sleep(0.5)


async def example_metrics_comparison() -> None:
    """Example showing metrics comparison."""
    print("\n" + "=" * 60)
    print("Example 5: Metrics Comparison")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Create two bridges with different configurations
    bridge1 = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=BridgeConfig(rx_queue_size=1000),
    )

    bridge2 = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan1",
        bridge_config=BridgeConfig(rx_queue_size=5000),
    )

    await bridge1.initialize()
    await bridge2.initialize()

    metrics1 = bridge1.metrics
    metrics2 = bridge2.metrics

    print("\nBridge 1 Metrics:")
    print(f"  Queue Size Config: {bridge1._bridge_config.rx_queue_size}")
    print(f"  Queue Depth: {metrics1.rx_queue_depth}")
    print(f"  Health: {metrics1.is_healthy}")

    print("\nBridge 2 Metrics:")
    print(f"  Queue Size Config: {bridge2._bridge_config.rx_queue_size}")
    print(f"  Queue Depth: {metrics2.rx_queue_depth}")
    print(f"  Health: {metrics2.is_healthy}")

    print("\nComparison:")
    print(f"  Both Healthy: {metrics1.is_healthy and metrics2.is_healthy}")
    print(f"  Same State: {metrics1.connection_state == metrics2.connection_state}")


async def example_typed_metrics() -> None:
    """Example showing type safety benefits."""
    print("\n" + "=" * 60)
    print("Example 6: Type Safety Benefits")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    bridge = AmpioBridge(cfg, interface="virtual", channel="vcan0")
    await bridge.initialize()

    # Get metrics - IDE knows the type!
    metrics = bridge.metrics

    print("\nType-safe attribute access:")
    print(f"  Connected (bool): {metrics.connected}")
    print(f"  RX Total (int): {metrics.rx_total}")
    print(f"  RX Rate (float): {metrics.rx_rate_s}")
    print(f"  Session ID (str | None): {metrics.session_id}")

    print("\nType-safe computed properties:")
    print(f"  is_healthy (bool): {metrics.is_healthy}")
    print(f"  has_recent_rx (bool): {metrics.has_recent_rx}")
    print(f"  error_rate (float): {metrics.error_rate}")
    print(f"  drop_rate (float): {metrics.drop_rate}")

    print("\nAdvantages:")
    print("  ✓ IDE autocomplete for all attributes")
    print("  ✓ Type checker validates access patterns")
    print("  ✓ Computed properties provide insights")
    print("  ✓ No dict key typos possible")


async def example_metrics_persistence() -> None:
    """Example showing metrics serialization."""
    print("\n" + "=" * 60)
    print("Example 7: Metrics Serialization")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    bridge = AmpioBridge(cfg, interface="virtual", channel="vcan0")
    await bridge.initialize()

    metrics = bridge.metrics

    # Convert to dict for serialization
    metrics_dict = metrics.to_dict()

    print("\nMetrics ready for serialization:")
    print(f"  Type: {type(metrics_dict).__name__}")
    print(f"  Keys: {len(metrics_dict)}")

    # Simulate JSON serialization
    import json

    try:
        json_str = json.dumps(metrics_dict, indent=2, default=str)
        print(f"\nJSON serialization successful ({len(json_str)} chars)")
        print("Sample JSON output:")
        lines = json_str.split("\n")[:10]
        for line in lines:
            print(f"  {line}")
        if len(json_str.split("\n")) > 10:
            print("  ...")
    except Exception as e:
        print(f"\nJSON serialization failed: {e}")


async def main() -> None:
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Structured Metrics Examples")
    print("=" * 60)

    await example_basic_metrics()
    await example_health_checks()
    await example_metrics_dict()
    await example_health_monitoring()
    await example_metrics_comparison()
    await example_typed_metrics()
    await example_metrics_persistence()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
