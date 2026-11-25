# aioampio

An asyncio library for Ampio devices using python-can. Requires Python 3.12 or newer; Python 3.12, 3.13, and 3.14 are tested in CI.

## Version 2 beta

Version 2 changes the constructor, metrics, and alarm-state APIs. Test the beta in a development environment before updating an integration. The published Ampio Home Assistant integration remains pinned to the stable 1.0.x library until its version 2 validation is complete.

```sh
python -m pip install aioampio==2.0.0b1
```

## Connect to a gateway

Load an Ampio YAML configuration, initialize the resources, and then start the connection. Always stop the bridge in a finally block.

```python
import asyncio
from pathlib import Path

import yaml

from aioampio import AmpioBridge
from aioampio.bridge_config import BridgeConfig


async def main():
    config = yaml.safe_load(
        await asyncio.to_thread(Path("config.yaml").read_text, encoding="utf-8")
    )
    bridge = AmpioBridge(
        config,
        interface="waveshare",
        channel="can0",
        host="192.0.2.1",
        port=20001,
        bridge_config=BridgeConfig(),
    )
    try:
        await bridge.initialize()
        await bridge.start()
        if not await bridge.wait_connected(timeout=10):
            raise TimeoutError("Ampio gateway did not connect")
        await asyncio.Event().wait()
    finally:
        await bridge.stop()


asyncio.run(main())
```

For SocketCAN, use interface="socketcan" and channel="can0" without network arguments. For in-process tests, use interface="virtual" and a shared channel name. Backend-specific keyword arguments are forwarded to python-can.

CAN reception uses python-can's notifier thread. Decoding, state updates, and callbacks run on the asyncio event loop. RX workers yield between bounded batches. Blocking bus construction, transmission, and teardown run in executor threads.

## Command line

The CLI validates configuration or starts a receive-only bridge. It does not send actuator commands.

```sh
# Validate YAML without opening a CAN connection.
aioampio --config config.yaml --validate

# Use a Waveshare gateway.
aioampio --config config.yaml --host 192.0.2.1 --port 20001

# Use another python-can backend.
aioampio --config config.yaml --interface socketcan --channel vcan0

# Use a virtual bus for local testing.
aioampio --config config.yaml --interface virtual --channel test
```

Waveshare is the default interface and requires a host. Its default remote port is 20001. Other backends receive host and port only when supplied, preserving their own defaults. Press Ctrl+C to stop and clean up the bridge.

## Migrating from 1.0.x

### Constructor

Replace positional host and port arguments:

```python
# Version 1
bridge = AmpioBridge(config, "192.0.2.1", 20001)

# Version 2
bridge = AmpioBridge(
    config, interface="waveshare", channel="can0", host="192.0.2.1", port=20001
)
```

Use BridgeConfig for connection timeouts, watchdogs, worker counts, and queue limits. These settings are separate from backend-specific keyword arguments.

### Metrics

The metrics property returns a BridgeMetrics snapshot. Request a new snapshot when reading current counters.

```python
snapshot = bridge.metrics
print(snapshot.connected, snapshot.rx_total, snapshot.connection_state)

# For dictionary consumers, replace bridge.metrics["rx_total"] with:
print(bridge.get_metrics_dict()["rx_total"])
```

### Alarm state

Replace alarm.state access with alarm.get_state(). It returns the armed, arming, arming_10s, breached, and alarm flags. Each flag can be None until its first update.

```python
state = alarm.get_state()
armed = state["armed"]
```

## Development

```sh
python -m pip install -e . pytest==8.4.2 pytest-asyncio==1.2.0 pytest-cov==7.0.0
pytest tests/
```

The full suite runs against virtual CAN or mocked buses and does not send commands to physical devices. CI runs the suite on Python 3.12, 3.13, and 3.14. A separate Python 3.13 lint job runs the repository pre-commit hooks; both tests and lint must pass before PyPI publication.
