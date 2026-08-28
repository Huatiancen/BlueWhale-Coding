from pathlib import Path

import pytest
import uvicorn
from fastapi import FastAPI

from bluewhale_agent.cli import build_parser, main


def test_serve_command_accepts_workspace() -> None:
    args = build_parser().parse_args(["serve", "--workspace", "."])

    assert args.command == "serve"
    assert args.workspace == "."


def test_desktop_command_needs_no_workspace() -> None:
    args = build_parser().parse_args(["desktop"])

    assert args.command == "desktop"


def test_main_dispatches_desktop_command(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("bluewhale_agent.desktop.launcher.run_desktop", lambda: 7)

    assert main(["desktop"]) == 7


def test_main_starts_local_uvicorn_server(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    received: dict[str, object] = {}

    def fake_run(app: FastAPI, *, host: str, port: int) -> None:
        received.update({"app": app, "host": host, "port": port})

    monkeypatch.setattr(uvicorn, "run", fake_run)

    exit_code = main(["serve", "--workspace", str(tmp_path), "--port", "9000"])

    assert exit_code == 0
    assert isinstance(received["app"], FastAPI)
    assert received["host"] == "127.0.0.1"
    assert received["port"] == 9000
    assert "http://127.0.0.1:9000" in capsys.readouterr().out


def test_main_rejects_missing_workspace(tmp_path: Path) -> None:
    with pytest.raises(SystemExit) as error:
        main(["serve", "--workspace", str(tmp_path / "missing")])

    assert error.value.code == 2
