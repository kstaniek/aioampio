# Changelog

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
