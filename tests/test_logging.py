"""Verify library logging follows the namespace declared by integrations."""

import pytest

from aioampio import AmpioBridge


def test_library_logger_controls_bridge_messages(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Configuring aioampio must include bridge and controller logs."""
    bridge = AmpioBridge({}, interface="virtual", channel="logging-test")
    caplog.set_level("INFO", logger="aioampio")
    bridge.logger.info("Bridge namespace check")
    bridge.logger.getChild("light").info("Controller namespace check")
    assert [record.message for record in caplog.records] == [
        "Bridge namespace check",
        "Controller namespace check",
    ]
