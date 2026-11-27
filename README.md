# aioampio

An asyncio library for Ampio devices using python-can. Requires Python 3.12 or newer; Python 3.12, 3.13, and 3.14 are tested in CI.

## Library boundary

`aioampio` is a standalone asyncio library. It owns CAN transport, Ampio frame
encoding and decoding, resource models, state notifications, and commands.
It must run without Home Assistant installed and must not import Home Assistant
or depend on its event bus, registries, entities, or configuration entries.

Consumer integrations adapt the public library API to their own lifecycle and
state model. Home Assistant entities, service mappings, fixtures, and compatibility
tests belong in `hacs-ampio`, not in this package. Library tests use synthetic CAN
frames and callbacks; `tests/test_library_boundary.py` additionally blocks Home
Assistant imports in a fresh interpreter while initializing the library.

## Version 2

### Native MLED light groups (2.2.0)

Add `light_groups` alongside a model-17 device's ordinary `lights`:

```yaml
light_groups:
  - id: sofa
    name: MLED Sofa
    members: [light11, light12, light13, light14, light15, light16]
    area: Salon
```

Members must be existing non-RGBW dimmable lights on that module, with distinct
command outputs in 1–16. Local and already qualified member IDs are accepted.
The group is an additional resource in `bridge.lights`, with an ID such as
`00001e5f_light_group_sofa` and resolved `members`. Existing member IDs and
commands are preserved. Unsupported models, missing or duplicate members,
nested groups, output bounds, and resource-ID collisions fail validation.

`await bridge.lights.set_state(group_id, on=True, brightness=128)` sends exactly
one `0x14` frame with a little-endian mask (0xFC00 for outputs 11–16). Plain
library on uses 255 and off uses 0; consumers may remember their own shared
brightness setpoint. Group commands do not fan out or generate optimistic state.

Received member resource updates synchronously recompute containing groups,
including overlapping memberships. Group power is on if any member is known
on, off if all are known off, and otherwise unknown. Brightness is the rounded
mean of known levels of on members, zero when known off, and otherwise unknown.
The library retains individual feedback routing and emits group resource
updates only when aggregate state changes. It imports no Home Assistant APIs.

Exact frame tests, invalid configuration cases, overlapping feedback, deletion,
cleanup, and failure behavior are covered by `tests/test_light_groups.py`.
The command format was also accepted on MLED module 7775 (PCB 8, firmware 11701)
on 2026-11-26: Kitchen mask 0x03FF and Sofa mask 0xFC00 passed on, off, and
brightness 128 with per-output RX feedback and user visual checks.

Version 2 changes the constructor, metrics, and alarm-state APIs. See the
migration guide below when upgrading from 1.0.x. Home Assistant users should
upgrade through hacs-ampio 0.2.0 or newer, which adapts these APIs and provides
passive module availability monitoring.

```sh
python -m pip install aioampio==2.0.0
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

Configure the aioampio logger to control library messages. Bridge and controller loggers are its children, for example aioampio.can0 and aioampio.can0.light. Replace old aioampio[can0] logging overrides with aioampio or aioampio.can0.

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

### Module traffic

`bridge.module_metrics` returns a new dictionary keyed by configured module CAN
IDs. Its frozen `ModuleMetrics` snapshots expose `rx_total`, `tx_total`,
`last_rx_age_s`, and `last_rx_at`. Read snapshots on the bridge event loop; consumers do not
receive a callback for every frame and choose their own publishing interval.
This API contains no Home Assistant dependencies or availability policy.

```python
for can_id, module in bridge.module_metrics.items():
    print(f"{can_id:08x}", module.rx_total, module.tx_total, module.last_rx_age_s)
```

RX counts structurally valid frames at reader ingress, before queue drops,
decoding, and state deduplication. Only configured source IDs count. TX counts
successful bridge sends addressed to a configured module, including each
multi-frame fragment. Failed or dropped sends do not count; cancellation still
accounts for an executor send that actually completes. A successful send is not
an acknowledgement from the destination and does not refresh RX age.

Counters live for the bridge instance and survive reconnects. Each connection
session clears RX ages, so `None` means no fresh frame from that module in this
session. Ages use a monotonic clock and are independent of wall-clock changes.
`last_rx_at` is an aware UTC reception timestamp retained across reconnects,
including while RX ages reset to `None`. It starts as `None` before the first
frame. Global `bridge.metrics.last_rx_at` covers all reader ingress and is
serialized as an ISO 8601 string in `to_dict()`.

Silence no longer triggers reconnects with default `BridgeConfig` settings:
`idle_reconnect_s`, `rx_gap_reconnect_s`, and `max_no_rx_after_connect_s` now
all default to `None`. An unpowered module or broken CAN bus is not evidence
of a broken TCP connection. Applications can implement passive availability
checks using per-module RX ages. Reported notifier/socket errors, closed
transport descriptors, failed workers, and explicit reconnect requests still
recover the connection. Legacy silence reconnect timers remain available only
when explicitly configured.

### Alarm state

Replace alarm.state access with alarm.get_state(). It returns the armed, arming, arming_10s, breached, and alarm flags. Each flag can be None until its first update.

```python
state = alarm.get_state()
armed = state["armed"]
```

## Development

### Native masked light groups

Add `light_groups` beside a device's ordinary `lights`. MLED (model 17) supports
non-RGBW dimmable members on outputs 1–16. Version 2.3.0 adds MREL8S (model 4)
binary members on outputs 1–8:

```yaml
light_groups:
  - id: garaz
    name: Garaż
    area: Garaż
    members: [light3, light5, light6]
```

Members reference existing local light IDs on the same module. Their numeric
suffix selects the physical output, independent of feedback offsets such as
`binout.27`. This example uses mask `0x0034`. Each on/off action sends one
`0x14` frame with value 255/0. Relay groups reject intermediate brightness;
MLED groups also accept a shared brightness level. Individual controls remain.
Group power follows member feedback: any on, all off, otherwise unknown.
Relay groups have no brightness state. Group IDs remain stable across renames.

The unreleased `members_enabled` option defaults to `true`. Set
`members_enabled: false` on a group to let Home Assistant initially register its
individual members as disabled. All member resources and feedback subscriptions
remain active in this library, so native group feedback and commands still work.
The library exposes the setting on the group resource; Home Assistant applies
the registry default and preserves existing user choices. If groups overlap,
HA defaults a member to disabled when any containing group sets this to false.
The independent `members_visible` option also defaults to `true`. Setting it to
`false` lets Home Assistant hide members while keeping them enabled. This is
recommended for members that should retain state, history and direct controls
but be omitted from automatic dashboards and area/device/label targets. For
example, use `members_enabled: true` with `members_visible: false`. Both defaults
preserve saved registry choices; overlapping groups use `false` if any containing
group requests it. Use YAML booleans; strings such as `"false"` are rejected.

### Test suite

```sh
python -m pip install -e . pytest==8.4.2 pytest-asyncio==1.2.0 pytest-cov==7.0.0
pytest tests/
```

The full suite runs against virtual CAN or mocked buses and does not send commands to physical devices. CI runs the suite on Python 3.12, 3.13, and 3.14. A separate Python 3.13 lint job runs the repository pre-commit hooks; both tests and lint must pass before PyPI publication.

## Command errors

Version 2.0.2 exports `AmpioTransmissionError` from `aioampio`. It subclasses
`ConnectionError` and is raised by `AmpioBridge.send()` and controller commands
when the transport rejects a frame or a CAN write fails. Callers should catch
this error and report or handle the failed command. Multi-frame commands stop
at the first failed frame; already submitted frames cannot be rolled back.
Successful submission means the transport accepted the frame, not that the
module received or executed it. Versions through 2.0.1 log these failures but do not propagate this exception.

## Reconnect notifications (2.1.0)

`bridge.subscribe_reconnects(callback)` returns an idempotent unsubscribe function.
The synchronous callback receives the new integer count on the bridge event loop
as soon as a retry cycle is recorded, before backoff starts. Keep callbacks short
and nonblocking. Subscriber exceptions are logged without interrupting transport
recovery. Subscribe does not emit an initial value; read
`bridge.metrics.reconnects` for the current count. The initial connection is not
counted; failed retry cycles are counted. The counter lasts for the bridge
instance, including stop/start, and starts at zero for a new instance.
