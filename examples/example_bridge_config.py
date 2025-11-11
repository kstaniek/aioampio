"""Example showing BridgeConfig usage."""
# pylint: disable=protected-access  # Accessing _bridge_config for demonstration

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import yaml

from aioampio import AmpioBridge
from aioampio.bridge import BridgeConfig

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


async def example_default_config() -> None:
    """Example using default configuration."""
    print("\n" + "=" * 60)
    print("Example 1: Default Configuration")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Create bridge with default configuration
    bridge = AmpioBridge(cfg, interface="virtual", channel="vcan0")

    # BridgeConfig will use all defaults:
    # - read_timeout_s: 2.0
    # - reconnect_initial_s: 0.5
    # - reconnect_max_s: 30.0
    # - idle_reconnect_s: 60.0
    # - etc.

    print(f"Default config: {bridge._bridge_config}")
    await bridge.initialize()
    print("✓ Bridge initialized with default configuration")


async def example_custom_config() -> None:
    """Example using custom configuration."""
    print("\n" + "=" * 60)
    print("Example 2: Custom Configuration")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Create custom configuration for production use
    bridge_config = BridgeConfig(
        # Longer read timeout for slower networks
        read_timeout_s=5.0,
        # More aggressive reconnection
        reconnect_initial_s=1.0,
        reconnect_max_s=60.0,
        # Larger queue for high-traffic scenarios
        rx_queue_size=5000,
        bounded_reader_size=10000,
        # More reactive rate smoothing
        rate_smoothing_alpha=0.8,
        # Multiple RX workers for better throughput
        rx_worker_count=2,
    )

    bridge = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=bridge_config,
    )

    print(f"Custom config: {bridge._bridge_config}")
    await bridge.initialize()
    print("✓ Bridge initialized with custom configuration")


async def example_disabled_watchdogs() -> None:
    """Example disabling watchdog timeouts."""
    print("\n" + "=" * 60)
    print("Example 3: Disabled Watchdogs")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Disable all watchdog timeouts (useful for testing)
    bridge_config = BridgeConfig(
        idle_reconnect_s=None,  # No idle reconnect
        rx_gap_reconnect_s=None,  # No RX gap reconnect
        max_no_rx_after_connect_s=None,  # No notifier stall detection
    )

    bridge = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=bridge_config,
    )

    print(f"Config with disabled watchdogs: {bridge._bridge_config}")
    await bridge.initialize()
    print("✓ Bridge initialized without watchdog timeouts")


async def example_validation_error() -> None:
    """Example showing configuration validation."""
    print("\n" + "=" * 60)
    print("Example 4: Configuration Validation")
    print("=" * 60)

    try:
        # This will fail validation: initial > max
        invalid_config = BridgeConfig(
            reconnect_initial_s=60.0,
            reconnect_max_s=10.0,
        )
        print(f"Invalid config: {invalid_config}")
    except ValueError as e:
        print(f"✓ Validation caught invalid configuration:\n{e}")

    try:
        # This will fail validation: negative timeout
        invalid_config = BridgeConfig(read_timeout_s=-1.0)
        print(f"Invalid config: {invalid_config}")
    except ValueError as e:
        print(f"✓ Validation caught invalid configuration:\n{e}")

    try:
        # This will fail validation: alpha out of range
        invalid_config = BridgeConfig(rate_smoothing_alpha=1.5)
        print(f"Invalid config: {invalid_config}")
    except ValueError as e:
        print(f"✓ Validation caught invalid configuration:\n{e}")


async def example_minimal_config() -> None:
    """Example using minimal configuration for testing."""
    print("\n" + "=" * 60)
    print("Example 5: Minimal Configuration (Testing)")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Minimal configuration for fast unit tests
    bridge_config = BridgeConfig(
        read_timeout_s=0.1,  # Very short timeout
        reconnect_initial_s=0.1,
        reconnect_max_s=1.0,
        idle_reconnect_s=None,  # Disable watchdogs
        rx_gap_reconnect_s=None,
        max_no_rx_after_connect_s=None,
        rx_queue_size=100,  # Small queues
        bounded_reader_size=200,
    )

    bridge = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=bridge_config,
    )

    print(f"Minimal test config: {bridge._bridge_config}")
    await bridge.initialize()
    print("✓ Bridge initialized with minimal configuration for testing")


async def main() -> None:
    """Run all examples."""
    print("\n" + "=" * 60)
    print("BridgeConfig Examples")
    print("=" * 60)

    await example_default_config()
    await example_custom_config()
    await example_disabled_watchdogs()
    await example_validation_error()
    await example_minimal_config()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
