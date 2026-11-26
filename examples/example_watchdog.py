"""Example demonstrating watchdog system functionality."""
# pylint: disable=protected-access  # Accessing internals for demonstration

from __future__ import annotations

import asyncio
import logging
import time
from pathlib import Path

import yaml

from aioampio import AmpioBridge
from aioampio.bridge import (
    BridgeConfig,
    IdleWatchdog,
    NotifierStallWatchdog,
    RxGapWatchdog,
    WatchdogManager,
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
)


async def example_watchdog_classes() -> None:
    """Example showing individual watchdog classes."""
    print("\n" + "=" * 60)
    print("Example 1: Individual Watchdog Classes")
    print("=" * 60)

    logger = logging.getLogger("watchdog-demo")
    reconnect_event = asyncio.Event()

    # Create individual watchdogs
    notifier_stall = NotifierStallWatchdog(logger, reconnect_event, timeout_s=5.0)
    rx_gap = RxGapWatchdog(logger, reconnect_event, timeout_s=10.0)
    idle = IdleWatchdog(logger, reconnect_event, timeout_s=60.0)

    print(f"Created NotifierStallWatchdog with {notifier_stall.timeout_s}s timeout")
    print(f"Created RxGapWatchdog with {rx_gap.timeout_s}s timeout")
    print(f"Created IdleWatchdog with {idle.timeout_s}s timeout")

    # Simulate scenarios
    now = time.monotonic()
    connected_since = now - 2.0  # Connected 2 seconds ago
    last_rx = None  # No messages received yet

    print("\nScenario 1: Just connected, no RX yet")
    print(
        f"  NotifierStallWatchdog: {notifier_stall.check(now, connected_since, last_rx)}"
    )
    print(f"  RxGapWatchdog: {rx_gap.check(now, connected_since, last_rx)}")
    print(f"  IdleWatchdog: {idle.check(now, connected_since, last_rx)}")

    # Simulate notifier stall (no RX after 6 seconds)
    print("\nScenario 2: Connected 6s ago, still no RX (notifier stall)")
    connected_since = now - 6.0
    result = notifier_stall.check(now, connected_since, last_rx)
    print(f"  NotifierStallWatchdog triggered: {result}")
    print(f"  Reconnect event set: {reconnect_event.is_set()}")

    reconnect_event.clear()

    # Simulate RX gap
    print("\nScenario 3: Last RX 12s ago (RX gap)")
    last_rx = now - 12.0
    result = rx_gap.check(now, connected_since, last_rx)
    print(f"  RxGapWatchdog triggered: {result}")
    print(f"  Reconnect event set: {reconnect_event.is_set()}")


async def example_watchdog_manager() -> None:
    """Example showing watchdog manager."""
    print("\n" + "=" * 60)
    print("Example 2: Watchdog Manager")
    print("=" * 60)

    logger = logging.getLogger("watchdog-manager-demo")
    reconnect_event = asyncio.Event()

    # Create manager and add watchdogs
    manager = WatchdogManager()
    manager.add_watchdog(NotifierStallWatchdog(logger, reconnect_event, 5.0))
    manager.add_watchdog(RxGapWatchdog(logger, reconnect_event, 10.0))
    manager.add_watchdog(IdleWatchdog(logger, reconnect_event, 60.0))

    print(f"Manager has {len(manager._watchdogs)} watchdogs")
    print(f"Manager enabled: {manager.is_enabled()}")

    # Check all watchdogs
    now = time.monotonic()
    connected_since = now - 6.0  # Will trigger notifier stall
    last_rx = None

    print("\nChecking all watchdogs (connected 6s ago, no RX)...")
    triggered = manager.check_all(now, connected_since, last_rx)
    print(f"Any watchdog triggered: {triggered}")
    print(f"Reconnect event set: {reconnect_event.is_set()}")


async def example_bridge_with_custom_watchdogs() -> None:
    """Example showing bridge with custom watchdog configuration."""
    print("\n" + "=" * 60)
    print("Example 3: Bridge with Custom Watchdog Configuration")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Create bridge with aggressive watchdog timeouts
    bridge_config = BridgeConfig(
        max_no_rx_after_connect_s=2.0,  # Quick notifier stall detection
        rx_gap_reconnect_s=5.0,  # Short gap tolerance
        idle_reconnect_s=30.0,  # Quick idle detection
    )

    bridge = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=bridge_config,
    )

    print(f"Bridge created with {len(bridge._watchdog_manager._watchdogs)} watchdogs")
    print("Watchdog configuration:")
    for i, watchdog in enumerate(bridge._watchdog_manager._watchdogs, 1):
        timeout = getattr(watchdog, "timeout_s", "N/A")
        print(f"  {i}. {watchdog.__class__.__name__}: {timeout}s")

    await bridge.initialize()
    print("✓ Bridge initialized with custom watchdog configuration")


async def example_bridge_no_watchdogs() -> None:
    """Example showing bridge with all watchdogs disabled."""
    print("\n" + "=" * 60)
    print("Example 4: Bridge with No Watchdogs (Testing)")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Disable all watchdogs
    bridge_config = BridgeConfig(
        max_no_rx_after_connect_s=None,
        rx_gap_reconnect_s=None,
        idle_reconnect_s=None,
    )

    bridge = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=bridge_config,
    )

    print(f"Bridge created with {len(bridge._watchdog_manager._watchdogs)} watchdogs")
    print(f"Watchdogs enabled: {bridge._watchdog_manager.is_enabled()}")

    await bridge.initialize()
    print("✓ Bridge initialized with no watchdogs (suitable for testing)")


async def example_selective_watchdogs() -> None:
    """Example showing bridge with selective watchdog enabling."""
    print("\n" + "=" * 60)
    print("Example 5: Bridge with Selective Watchdogs")
    print("=" * 60)

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    # Enable only idle watchdog (production scenario)
    bridge_config = BridgeConfig(
        max_no_rx_after_connect_s=None,  # Disabled
        rx_gap_reconnect_s=None,  # Disabled
        idle_reconnect_s=300.0,  # 5 minutes - only long-term issues
    )

    bridge = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=bridge_config,
    )

    print(f"Bridge created with {len(bridge._watchdog_manager._watchdogs)} watchdog(s)")
    print("Active watchdogs:")
    for watchdog in bridge._watchdog_manager._watchdogs:
        timeout = getattr(watchdog, "timeout_s", "N/A")
        print(f"  - {watchdog.__class__.__name__}: {timeout}s")

    await bridge.initialize()
    print("✓ Bridge initialized with only idle watchdog enabled")


async def example_watchdog_hierarchy() -> None:
    """Example showing watchdog timing hierarchy."""
    print("\n" + "=" * 60)
    print("Example 6: Watchdog Timing Hierarchy")
    print("=" * 60)

    # Demonstrate typical hierarchy
    print("Typical watchdog timeout hierarchy:")
    print("  1. NotifierStallWatchdog: 5-10s (fastest detection)")
    print("     → Catches immediate notifier problems")
    print()
    print("  2. RxGapWatchdog: 10-30s (medium detection)")
    print("     → Catches transient connection issues")
    print()
    print("  3. IdleWatchdog: 60-300s (slowest detection)")
    print("     → Catches long-term silent failures")
    print()
    print("Best practice: NotifierStall < RxGap < Idle")

    config_path = Path(__file__).parent / "config.yaml"
    config_text = config_path.read_text(encoding="utf-8")
    cfg = yaml.safe_load(config_text)

    bridge_config = BridgeConfig(
        max_no_rx_after_connect_s=5.0,  # Fastest
        rx_gap_reconnect_s=15.0,  # Medium
        idle_reconnect_s=60.0,  # Slowest
    )

    bridge = AmpioBridge(
        cfg,
        interface="virtual",
        channel="vcan0",
        bridge_config=bridge_config,
    )

    print("\nConfigured hierarchy:")
    for watchdog in bridge._watchdog_manager._watchdogs:
        name = watchdog.__class__.__name__
        timeout = getattr(watchdog, "timeout_s", "N/A")
        print(f"  - {name}: {timeout}s")

    await bridge.initialize()
    print("✓ Bridge initialized with proper timing hierarchy")


async def main() -> None:
    """Run all examples."""
    print("\n" + "=" * 60)
    print("Watchdog System Examples")
    print("=" * 60)

    await example_watchdog_classes()
    await example_watchdog_manager()
    await example_bridge_with_custom_watchdogs()
    await example_bridge_no_watchdogs()
    await example_selective_watchdogs()
    await example_watchdog_hierarchy()

    print("\n" + "=" * 60)
    print("All examples completed!")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
