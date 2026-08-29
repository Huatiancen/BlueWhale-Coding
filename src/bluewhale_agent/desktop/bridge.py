"""Minimal native API exposed to the PyWebView renderer."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Protocol

from bluewhale_agent.desktop.grants import WorkspaceGrantError, WorkspaceGrantRegistry
from bluewhale_agent.desktop.secrets import SecretStore, SecretStoreError


class FolderPicker(Protocol):
    def choose_directory(self) -> str | None: ...


class WebViewWindow(Protocol):
    def create_file_dialog(
        self,
        dialog_type: object,
        *,
        allow_multiple: bool,
    ) -> object: ...


class PyWebViewFolderPicker:
    """Adapter around a PyWebView window's native folder dialog."""

    def __init__(self, folder_dialog_type: object) -> None:
        self._folder_dialog_type = folder_dialog_type
        self._window: WebViewWindow | None = None

    def attach(self, window: WebViewWindow) -> None:
        self._window = window

    def choose_directory(self) -> str | None:
        if self._window is None:
            return None
        selected = self._window.create_file_dialog(
            self._folder_dialog_type,
            allow_multiple=False,
        )
        if not selected:
            return None
        if isinstance(selected, (list, tuple)):
            return str(selected[0]) if selected else None
        return str(selected)


class DesktopBridge:
    """Expose only user-mediated workspace and secret operations to JavaScript."""

    def __init__(
        self,
        *,
        picker: FolderPicker,
        grants: WorkspaceGrantRegistry,
        secrets: SecretStore,
        has_active_run: Callable[[], bool],
        import_workspace_history: Callable[[Path], object] | None = None,
        resolve_history_workspace: Callable[[str], Path | None] | None = None,
    ) -> None:
        self._picker = picker
        self._grants = grants
        self._secrets = secrets
        self._has_active_run = has_active_run
        self._import_workspace_history = import_workspace_history
        self._resolve_history_workspace = resolve_history_workspace

    def select_workspace(self) -> dict[str, object]:
        if self._has_active_run():
            return {
                "ok": False,
                "error": "Stop the active task before switching projects",
            }
        selected = self._picker.choose_directory()
        if selected is None:
            return {"ok": True, "cancelled": True}
        try:
            grant = self._grants.grant(selected)
        except WorkspaceGrantError:
            return {"ok": False, "error": "Unable to open the selected project"}
        if self._import_workspace_history is not None:
            self._import_workspace_history(grant.path)
        return {
            "ok": True,
            "cancelled": False,
            "grant_id": grant.id,
            "display_name": grant.display_name,
            "display_path": str(grant.path),
        }

    def workspace_state(self) -> dict[str, object]:
        grant = self._grants.current()
        if grant is None:
            return {"ok": True, "configured": False}
        return {
            "ok": True,
            "configured": True,
            "grant_id": grant.id,
            "display_name": grant.display_name,
            "display_path": str(grant.path),
        }

    def activate_history_workspace(self, run_id: str) -> dict[str, object]:
        """Grant the workspace owned by a user-selected local history record."""
        if self._has_active_run():
            return {
                "ok": False,
                "error": "Stop the active task before switching projects",
            }
        if self._resolve_history_workspace is None:
            return {"ok": False, "error": "Historical task is unavailable"}
        workspace = self._resolve_history_workspace(run_id)
        if workspace is None:
            return {"ok": False, "error": "Historical task is unavailable"}
        try:
            grant = self._grants.grant(workspace)
        except WorkspaceGrantError:
            return {"ok": False, "error": "Historical workspace is unavailable"}
        return {
            "ok": True,
            "configured": True,
            "grant_id": grant.id,
            "display_name": grant.display_name,
            "display_path": str(grant.path),
        }

    def secret_state(self) -> dict[str, object]:
        try:
            configured = self._secrets.has_api_key()
        except SecretStoreError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "configured": configured}

    def save_api_key(self, value: str) -> dict[str, object]:
        try:
            self._secrets.set_api_key(value)
        except SecretStoreError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "configured": True}

    def clear_api_key(self) -> dict[str, object]:
        try:
            self._secrets.clear_api_key()
        except SecretStoreError as error:
            return {"ok": False, "error": str(error)}
        return {"ok": True, "configured": False}
