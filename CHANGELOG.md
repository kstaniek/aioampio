# Changelog

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
