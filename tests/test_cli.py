"""Exercise the installed CLI contract without opening hardware connections."""

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

from aioampio import cli


def test_validate_does_not_create_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Validate a configuration without requiring a host or accessing CAN."""
    config = tmp_path / "config.yaml"
    config.write_text("devices: []\n", encoding="utf-8")
    constructor = Mock()
    monkeypatch.setattr(cli, "AmpioBridge", constructor)
    cli.main(["--config", str(config), "--validate"])
    constructor.assert_not_called()


@pytest.mark.parametrize(
    ("arguments", "expected"),
    [
        pytest.param(
            ["--host", "192.0.2.1"],
            {
                "interface": "waveshare",
                "channel": "can0",
                "host": "192.0.2.1",
                "port": 20001,
            },
            id="waveshare-defaults",
        ),
        pytest.param(
            ["--interface", "waveshare", "--host", "192.0.2.1", "--port", "20002"],
            {
                "interface": "waveshare",
                "channel": "can0",
                "host": "192.0.2.1",
                "port": 20002,
            },
            id="waveshare-port",
        ),
        pytest.param(
            ["--interface", "virtual", "--channel", "test"],
            {"interface": "virtual", "channel": "test"},
            id="virtual-without-network-arguments",
        ),
        pytest.param(
            ["--interface", "socketcan", "--channel", "vcan0"],
            {"interface": "socketcan", "channel": "vcan0"},
            id="socketcan",
        ),
        pytest.param(
            ["--interface", "socketcand", "--host", "192.0.2.1"],
            {"interface": "socketcand", "channel": "can0", "host": "192.0.2.1"},
            id="preserve-backend-port-default",
        ),
    ],
)
def test_cli_uses_new_constructor_and_cleans_up(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    arguments: list[str],
    expected: dict[str, object],
) -> None:
    """Forward backend options and clean up on cancellation."""
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    bridge = Mock(
        initialize=AsyncMock(),
        start=AsyncMock(side_effect=asyncio.CancelledError),
        stop=AsyncMock(),
    )
    constructor = Mock(return_value=bridge)
    monkeypatch.setattr(cli, "AmpioBridge", constructor)
    with pytest.raises(asyncio.CancelledError):
        cli.main(["--config", str(config), *arguments])
    constructor.assert_called_once_with({}, **expected)
    bridge.initialize.assert_awaited_once_with()
    bridge.stop.assert_awaited_once_with()


def test_cli_initialization_error_still_stops_bridge(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Release resources even if initialization fails before start."""
    config = tmp_path / "config.yaml"
    config.write_text("{}", encoding="utf-8")
    bridge = Mock(
        initialize=AsyncMock(side_effect=RuntimeError("Initialization failed")),
        start=AsyncMock(),
        stop=AsyncMock(),
    )
    monkeypatch.setattr(cli, "AmpioBridge", Mock(return_value=bridge))
    with pytest.raises(RuntimeError, match="Initialization failed"):
        cli.main(["--config", str(config), "--interface", "virtual"])
    bridge.start.assert_not_awaited()
    bridge.stop.assert_awaited_once_with()


def test_waveshare_requires_host(capsys: pytest.CaptureFixture[str]) -> None:
    """Explain the missing network parameter before reading configuration."""
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", "unused.yaml"])
    assert error.value.code == 2
    assert "--host is required" in capsys.readouterr().err


@pytest.mark.parametrize("port", ["0", "65536"])
def test_invalid_port_is_reported(
    port: str, capsys: pytest.CaptureFixture[str]
) -> None:
    """Reject invalid remote ports with a normal CLI error."""
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", "unused.yaml", "--host", "192.0.2.1", "--port", port])
    assert error.value.code == 2
    assert "--port must be between" in capsys.readouterr().err


def test_invalid_yaml_is_reported(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Report malformed input without opening a connection."""
    config = tmp_path / "config.yaml"
    config.write_text("devices: [", encoding="utf-8")
    with pytest.raises(SystemExit) as error:
        cli.main(["--config", str(config), "--validate"])
    assert error.value.code == 2
    assert "error:" in capsys.readouterr().err
