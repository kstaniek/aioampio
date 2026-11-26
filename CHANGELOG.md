# Changelog

## 2.0.0

- Promote the validated version 2 bridge and resource-model refactor to stable.
- Require explicit CAN interface/channel constructor arguments; expose structured
  `BridgeMetrics` and alarm `get_state()`. See the README migration guide.
- Serialize lifecycle transitions, preserve per-topic event order, await resource
  updates, and bound RX work so bursts do not starve the event loop.
- Keep blocking transport construction, sends and teardown off the event loop.
- Add immutable per-module RX/TX totals, monotonic RX ages and UTC last-frame
  timestamps; preserve counters across transport reconnects.
- Account for successful executor sends even when their callers are cancelled.
- Disable silence-triggered reconnect timers by default. A silent module or broken
  CAN bus does not prove a transport failure. Reported notifier/socket failures,
  closed descriptors and failed RX workers still recover the connection. Legacy
  silence reconnect timers remain available when explicitly configured.
- Keep the library standalone, with no Home Assistant dependency.

Acceptance used a packaged beta on Python 3.12–3.14 and HA 2026.11/development
Core. A temporary receive-only proxy confirmed module timeout and recovery
without gateway reconnects, plus independent EOF recovery. A guarded RGBW test on
module 00001879 confirmed command feedback and matching global/module TX counters,
then restored its original state. The Python implementation is unchanged from
2.0.0b4.

## 2.0.0b3 (pre-release)

- Await controller state updates within state-store notifications instead of
  creating a task for every topic change. Awaiting a state update now also
  completes the resource update and synchronous subscriber notification.
- Yield while transferring ready CAN frames and while dispatching decoded
  messages from a single frame. Both stages share the receive worker limits:
  16 items or 10 ms, checked between items.
- Add regressions for resource update completion, transport backlog fairness,
  and frames that decode into many topic updates.

The library remains independent of Home Assistant. Physical command acceptance
and the stable 2.0.0 release are deferred; this beta is for development testing.

## 2.0.0b2 (pre-release)

- Preserve per-topic notification order with asynchronous subscribers, including
  callback feedback and cancellation; allow unrelated topics to notify concurrently.
- Keep brightness and RGB channel values as integers so received values can be
  reused safely in commands; reject non-finite numeric values and invalid positions.
- Validate optional watchdog timeouts and handle a valid zero connection timestamp.
- Use one frame processor for bridge decoding, ignore CAN error frames, and remove
  the unused duplicate connection manager.
- Add standalone watchdog, state-store, model, wire-command, and frame regression
  tests. Enforce that the library initializes without Home Assistant imports.

Home Assistant adapters and compatibility tests remain in `hacs-ampio`. This
beta retains the version 2 API changes described below; stable integrations
should continue to use the 1.0.x library.

## 2.0.0b1 (pre-release)

- Serialize start and stop, allow restarting a stopped instance, and preserve valid connection state during reconnect and setup failures.
- Carry forward cancellation-safe bus creation and bounded RX batches from the 1.0.x maintenance releases.
- Reconnect after an RX worker reaches the configured consecutive-error limit.
- Coordinate sends and off-loop teardown through a shared bus lock, including cancelled sends and stop calls.
- Accept the first RGB update when a light has an empty initial state.
- Preserve validated resource defaults and restore mandatory test/lint gates before PyPI publication.

- Update the CLI to use interface/channel arguments, preserve backend network defaults, and clean up on cancellation or initialization failure.
- Declare the CLI YAML dependency and include the typing marker in distributions.
- Keep bridge and controller loggers under the aioampio namespace so integration logging settings apply.

Breaking changes: the constructor now requires interface/channel, metrics returns BridgeMetrics, and alarm state uses get_state(). See the migration guide in README.md. This beta is intended for development testing; stable Home Assistant installations should retain aioampio 1.0.x.

## 1.0.2

- Yield receive workers between bounded batches of queued CAN frames, allowing
  other asyncio tasks and shutdown requests to run during bursts. Workers yield
  after 16 frames or 10 ms of batch time, checked between frames, without dropping
  or reordering frames.

## 1.0.1

- Preserve validated configuration defaults when creating resources. Lights and
  switches without an explicit `on` capability now initialize successfully.
- Create CAN connections in a worker thread, avoiding blocking configuration-file
  reads and socket connection setup on the asyncio event loop.
- Close connections that finish opening after setup has been cancelled, including
  when the bridge is stopped during connection setup.
- Add regression coverage for configuration defaults, constructor compatibility,
  worker-thread connection setup, cancellation, and repeated start/stop cycles.
- Run the full test suite on Python 3.12, 3.13, and 3.14 before publishing to PyPI.

The public `AmpioBridge(cfg, host, port, ...)` API and resource models remain
compatible with 1.0.0. This maintenance release does not include the broader bridge
refactor.
