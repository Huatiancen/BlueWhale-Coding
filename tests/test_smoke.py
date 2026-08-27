import pytest

from bluewhale_agent.cli import build_parser, main


def test_serve_command_accepts_workspace() -> None:
    args = build_parser().parse_args(["serve", "--workspace", "."])

    assert args.command == "serve"
    assert args.workspace == "."


def test_main_reports_requested_server(capsys: pytest.CaptureFixture[str]) -> None:
    exit_code = main(["serve", "--workspace", ".", "--port", "9000"])

    assert exit_code == 0
    assert "http://127.0.0.1:9000" in capsys.readouterr().out
