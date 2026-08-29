from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest

from bluewhale_agent.config import Settings
from bluewhale_agent.desktop.launcher import (
    DesktopLaunchError,
    _confirm_desktop_close,
    desktop_history_root,
    run_desktop,
)
from bluewhale_agent.desktop.secrets import MemorySecretStore


class FakeEvent:
    def __init__(self) -> None:
        self.handlers: list[object] = []

    def __iadd__(self, handler: object) -> FakeEvent:
        self.handlers.append(handler)
        return self


class FakeWindow:
    def __init__(self) -> None:
        self.confirmations: list[tuple[str, str]] = []
        self.events = SimpleNamespace(closing=FakeEvent())

    def create_file_dialog(self, _kind: object, *, allow_multiple: bool) -> None:
        assert allow_multiple is False
        return None

    def create_confirmation_dialog(self, title: str, message: str) -> bool:
        self.confirmations.append((title, message))
        return False


class FakeWebView:
    FOLDER_DIALOG = "folder"

    def __init__(self, events: list[str]) -> None:
        self.events = events
        self.window = FakeWindow()
        self.created: dict[str, object] = {}

    def create_window(self, title: str, url: str, **options: object) -> FakeWindow:
        self.events.append("window")
        self.created = {"title": title, "url": url, **options}
        return self.window

    def start(self) -> None:
        self.events.append("webview")


class FakeController:
    def __init__(self, _app: object, events: list[str]) -> None:
        self.events = events
        self.base_url = "http://127.0.0.1:43210"

    def start(self) -> None:
        self.events.append("server-start")

    def stop(self) -> None:
        self.events.append("server-stop")


def settings() -> Settings:
    return Settings.model_construct(
        deepseek_api_key=None,
        model="test-model",
        base_url="https://api.deepseek.com",
        workspace=Path.cwd(),
        limits=Settings().limits,
    )


def test_run_desktop_orders_server_window_and_cleanup(tmp_path: Path) -> None:
    events: list[str] = []
    webview = FakeWebView(events)

    result = run_desktop(
        webview_module=webview,
        secret_store=MemorySecretStore(),
        settings=settings(),
        controller_factory=lambda app: FakeController(app, events),
        platform="darwin",
        history_root=tmp_path / "history",
    )

    assert result == 0
    assert events == ["server-start", "window", "webview", "server-stop"]
    assert webview.created["title"] == "BlueWhale Coding Agent"
    assert str(webview.created["url"]).startswith(
        "http://127.0.0.1:43210/desktop/bootstrap?token="
    )
    assert webview.created["js_api"] is not None
    assert len(webview.window.events.closing.handlers) == 1


def test_run_desktop_stops_server_when_webview_fails(tmp_path: Path) -> None:
    events: list[str] = []
    webview = FakeWebView(events)

    def fail() -> None:
        events.append("webview")
        raise RuntimeError("window failed")

    webview.start = fail
    with pytest.raises(RuntimeError, match="window failed"):
        run_desktop(
            webview_module=webview,
            secret_store=MemorySecretStore(),
            settings=settings(),
            controller_factory=lambda app: FakeController(app, events),
            platform="darwin",
            history_root=tmp_path / "history",
        )

    assert events[-1] == "server-stop"


def test_run_desktop_rejects_non_macos() -> None:
    with pytest.raises(DesktopLaunchError, match="requires macOS"):
        run_desktop(
            webview_module=SimpleNamespace(),
            secret_store=MemorySecretStore(),
            settings=settings(),
            platform="linux",
        )


def test_desktop_history_root_uses_macos_application_support(tmp_path: Path) -> None:
    assert desktop_history_root(tmp_path) == (
        tmp_path / "Library" / "Application Support" / "BlueWhale"
    )


def test_close_confirmation_is_only_shown_for_active_task() -> None:
    window = FakeWindow()

    assert _confirm_desktop_close(window, lambda: False) is True
    assert window.confirmations == []

    assert _confirm_desktop_close(window, lambda: True) is False
    assert window.confirmations == [
        (
            "停止任务并退出？",
            "BlueWhale 仍在执行任务。退出将停止任务并取消待审批操作。",
        )
    ]
