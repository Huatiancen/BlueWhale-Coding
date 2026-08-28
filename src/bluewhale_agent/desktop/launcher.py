"""macOS desktop application composition root."""

from __future__ import annotations

import importlib
import secrets
import sys
from collections.abc import Callable
from typing import Any, Protocol

from fastapi import FastAPI

from bluewhale_agent.config import Settings
from bluewhale_agent.desktop.bridge import DesktopBridge, PyWebViewFolderPicker
from bluewhale_agent.desktop.grants import WorkspaceGrantRegistry
from bluewhale_agent.desktop.secrets import (
    KeyringSecretStore,
    SecretStore,
    build_desktop_provider_factory,
)
from bluewhale_agent.desktop.server import LocalServerController
from bluewhale_agent.web.app import create_app
from bluewhale_agent.web.workspaces import GrantedWorkspaceResolver


class DesktopLaunchError(RuntimeError):
    """Raised when the native desktop application cannot be launched."""


class ServerController(Protocol):
    @property
    def base_url(self) -> str: ...

    def start(self) -> None: ...

    def stop(self) -> None: ...


class ConfirmationWindow(Protocol):
    def create_confirmation_dialog(self, title: str, message: str) -> bool: ...


ControllerFactory = Callable[[FastAPI], ServerController]


def run_desktop(
    *,
    webview_module: Any | None = None,
    secret_store: SecretStore | None = None,
    settings: Settings | None = None,
    controller_factory: ControllerFactory | None = None,
    platform: str | None = None,
) -> int:
    """Run BlueWhale in a native macOS WebKit window."""

    selected_platform = platform or sys.platform
    if selected_platform != "darwin":
        raise DesktopLaunchError("BlueWhale Desktop currently requires macOS")
    if webview_module is None:
        try:
            webview_module = importlib.import_module("webview")
        except ImportError as error:
            raise DesktopLaunchError(
                "Desktop dependencies are missing; install bluewhale-agent[desktop]"
            ) from error

    launch_token = secrets.token_urlsafe(32)
    grants = WorkspaceGrantRegistry()
    selected_store = secret_store or KeyringSecretStore()
    selected_settings = settings or Settings()
    app = create_app(
        workspace_resolver=GrantedWorkspaceResolver(grants),
        provider_factory=build_desktop_provider_factory(selected_store, selected_settings),
        settings=selected_settings,
        desktop_token=launch_token,
    )
    file_dialog = getattr(webview_module, "FileDialog", None)
    folder_dialog_type = (
        file_dialog.FOLDER if file_dialog is not None else webview_module.FOLDER_DIALOG
    )
    picker = PyWebViewFolderPicker(folder_dialog_type)
    bridge = DesktopBridge(
        picker=picker,
        grants=grants,
        secrets=selected_store,
        has_active_run=app.state.sessions.has_active_run,
    )
    selected_controller_factory = controller_factory or _create_server_controller
    controller = selected_controller_factory(app)
    controller.start()
    try:
        window = webview_module.create_window(
            "BlueWhale Coding Agent",
            f"{controller.base_url}/desktop/bootstrap?token={launch_token}",
            js_api=bridge,
            min_size=(1024, 700),
        )
        picker.attach(window)
        window.events.closing += lambda: _confirm_desktop_close(
            window,
            app.state.sessions.has_active_run,
        )
        webview_module.start()
    finally:
        controller.stop()
    return 0


def _create_server_controller(app: FastAPI) -> ServerController:
    return LocalServerController(app)


def _confirm_desktop_close(
    window: ConfirmationWindow,
    has_active_run: Callable[[], bool],
) -> bool:
    """Allow closing immediately unless an active run needs confirmation."""

    if not has_active_run():
        return True
    return window.create_confirmation_dialog(
        "停止任务并退出？",
        "BlueWhale 仍在执行任务。退出将停止任务并取消待审批操作。",
    )
