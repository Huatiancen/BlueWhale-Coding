"""macOS desktop application composition root."""

from __future__ import annotations

import importlib
import platform as platform_module
import secrets
import sys
from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol

from fastapi import FastAPI

from bluewhale_agent import __version__
from bluewhale_agent.config import Settings
from bluewhale_agent.desktop.bridge import DesktopBridge, PyWebViewFolderPicker
from bluewhale_agent.desktop.diagnostics import DiagnosticExporter
from bluewhale_agent.desktop.grants import WorkspaceGrantRegistry
from bluewhale_agent.desktop.preflight import PreflightRunner
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
    history_root: Path | None = None,
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
    selected_history_root = history_root or desktop_history_root()
    app = create_app(
        workspace_resolver=GrantedWorkspaceResolver(grants),
        provider_factory=build_desktop_provider_factory(selected_store, selected_settings),
        settings=selected_settings,
        desktop_token=launch_token,
        history_root=selected_history_root,
    )
    file_dialog = getattr(webview_module, "FileDialog", None)
    folder_dialog_type = (
        file_dialog.FOLDER if file_dialog is not None else webview_module.FOLDER_DIALOG
    )
    picker = PyWebViewFolderPicker(folder_dialog_type)
    preflight = PreflightRunner(secrets=selected_store, platform=selected_platform)
    diagnostic_exporter = DiagnosticExporter(
        version=__version__,
        platform_name=platform_module.platform(),
    )

    def write_diagnostics(destination: Path) -> Path:
        grant = grants.current()
        workspace = grant.path if grant is not None else None
        trajectory_summary, verification = _diagnostic_summaries(app.state.sessions)
        return diagnostic_exporter.export(
            destination,
            preflight=preflight.run(workspace).as_dict(),
            trajectory_summary=trajectory_summary,
            verification=verification,
        )

    bridge = DesktopBridge(
        picker=picker,
        grants=grants,
        secrets=selected_store,
        has_active_run=app.state.sessions.has_active_run,
        import_workspace_history=app.state.sessions.import_workspace_history,
        resolve_history_workspace=app.state.sessions.workspace_for_run,
        run_preflight=lambda workspace: preflight.run(workspace).as_dict(),
        write_diagnostics=write_diagnostics,
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


def desktop_history_root(home: Path | None = None) -> Path:
    """Return the application-owned history directory on macOS."""
    selected_home = home or Path.home()
    return selected_home / "Library" / "Application Support" / "BlueWhale"


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


def _diagnostic_summaries(sessions: Any) -> tuple[dict[str, object], dict[str, object]]:
    """Project the latest run into a bounded, source-free diagnostic summary."""
    available = sessions.list()
    if not available:
        return {}, {}
    latest = available[-1]
    response = latest.response()
    events = latest.trajectory.events_after(0)
    counts: dict[str, int] = {}
    for stored in events:
        key = stored.event.kind.value
        counts[key] = counts.get(key, 0) + 1
    trajectory = {
        "run_id": response.id,
        "status": response.status.value,
        "stop_reason": response.stop_reason.value if response.stop_reason is not None else None,
        "verified": response.verified,
        "steps_taken": response.steps_taken,
        "repair_attempts": response.repair_attempts,
        "event_count": len(events),
        "event_kind_counts": counts,
    }
    verification: dict[str, object] = {}
    for stored in reversed(events):
        if stored.event.kind.value != "verification_finished":
            continue
        raw = stored.event.payload.get("outcome")
        if not isinstance(raw, dict):
            break
        results = raw.get("latest_results")
        safe_results: list[dict[str, object]] = []
        if isinstance(results, list):
            for result in results:
                if not isinstance(result, dict):
                    continue
                safe_results.append(
                    {
                        "status": result.get("status"),
                        "exit_code": result.get("exit_code"),
                        "duration_ms": result.get("duration_ms"),
                    }
                )
        verification = {
            "passed": raw.get("passed"),
            "level": raw.get("level"),
            "stop_reason": raw.get("stop_reason"),
            "rounds": raw.get("rounds"),
            "repair_attempts": raw.get("repair_attempts"),
            "results": safe_results,
        }
        break
    return trajectory, verification
