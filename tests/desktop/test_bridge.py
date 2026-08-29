from __future__ import annotations

from pathlib import Path

from bluewhale_agent.desktop.bridge import DesktopBridge, PyWebViewFolderPicker
from bluewhale_agent.desktop.grants import WorkspaceGrantRegistry
from bluewhale_agent.desktop.secrets import MemorySecretStore


class FakeFolderPicker:
    def __init__(self, selected: Path | None) -> None:
        self.selected = selected

    def choose_directory(self) -> str | None:
        return str(self.selected) if self.selected is not None else None


class FakeWindow:
    def __init__(self, result: object) -> None:
        self.result = result

    def create_file_dialog(self, _dialog_type: object, *, allow_multiple: bool) -> object:
        assert allow_multiple is False
        return self.result


def build_bridge(
    selected: Path | None,
    *,
    active: bool = False,
) -> tuple[DesktopBridge, WorkspaceGrantRegistry, MemorySecretStore]:
    grants = WorkspaceGrantRegistry()
    secrets = MemorySecretStore()
    return (
        DesktopBridge(
            picker=FakeFolderPicker(selected),
            grants=grants,
            secrets=secrets,
            has_active_run=lambda: active,
        ),
        grants,
        secrets,
    )


def test_select_workspace_returns_opaque_grant(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    bridge, grants, _ = build_bridge(project)

    result = bridge.select_workspace()

    assert result["ok"] is True
    assert result["grant_id"]
    assert result["display_name"] == "demo"
    assert result["display_path"] == str(project.resolve())
    assert grants.resolve(str(result["grant_id"])) == project.resolve()


def test_select_workspace_imports_local_history_after_grant(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    imported: list[Path] = []
    grants = WorkspaceGrantRegistry()
    bridge = DesktopBridge(
        picker=FakeFolderPicker(project),
        grants=grants,
        secrets=MemorySecretStore(),
        has_active_run=lambda: False,
        import_workspace_history=lambda path: imported.append(path),
    )

    result = bridge.select_workspace()

    assert result["ok"] is True
    assert imported == [project.resolve()]


def test_activate_history_workspace_creates_grant_from_run_id(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    grants = WorkspaceGrantRegistry()
    bridge = DesktopBridge(
        picker=FakeFolderPicker(None),
        grants=grants,
        secrets=MemorySecretStore(),
        has_active_run=lambda: False,
        resolve_history_workspace=lambda run_id: project if run_id == "known" else None,
    )

    result = bridge.activate_history_workspace("known")

    assert result["ok"] is True
    assert result["grant_id"]
    assert result["display_path"] == str(project.resolve())
    assert grants.resolve(str(result["grant_id"])) == project.resolve()


def test_activate_history_workspace_rejects_unknown_or_missing_project(
    tmp_path: Path,
) -> None:
    missing = tmp_path / "missing"
    bridge = DesktopBridge(
        picker=FakeFolderPicker(None),
        grants=WorkspaceGrantRegistry(),
        secrets=MemorySecretStore(),
        has_active_run=lambda: False,
        resolve_history_workspace=lambda run_id: missing if run_id == "missing" else None,
    )

    unknown = bridge.activate_history_workspace("unknown")
    unavailable = bridge.activate_history_workspace("missing")

    assert unknown == {"ok": False, "error": "Historical task is unavailable"}
    assert unavailable == {"ok": False, "error": "Historical workspace is unavailable"}


def test_cancel_keeps_current_workspace_and_active_run_blocks_switch(tmp_path: Path) -> None:
    project = tmp_path / "demo"
    project.mkdir()
    bridge, grants, _ = build_bridge(project)
    first = bridge.select_workspace()

    cancelled = DesktopBridge(
        picker=FakeFolderPicker(None),
        grants=grants,
        secrets=MemorySecretStore(),
        has_active_run=lambda: False,
    ).select_workspace()
    active_bridge, _, _ = build_bridge(project, active=True)
    blocked = active_bridge.select_workspace()

    assert cancelled == {"ok": True, "cancelled": True}
    assert grants.current() is not None
    assert grants.current().id == first["grant_id"]
    assert blocked["ok"] is False
    assert "active task" in str(blocked["error"])


def test_invalid_workspace_returns_sanitized_error(tmp_path: Path) -> None:
    bridge, _, _ = build_bridge(tmp_path / "missing")

    result = bridge.select_workspace()

    assert result == {"ok": False, "error": "Unable to open the selected project"}


def test_secret_methods_never_return_key_value() -> None:
    bridge, _, secrets = build_bridge(None)

    saved = bridge.save_api_key("  desktop-key  ")
    state = bridge.secret_state()
    cleared = bridge.clear_api_key()

    assert saved == {"ok": True, "configured": True}
    assert state == {"ok": True, "configured": True}
    assert cleared == {"ok": True, "configured": False}
    assert secrets.get_api_key() is None
    assert "desktop-key" not in repr((saved, state, cleared))


def test_picker_requires_window_and_normalizes_native_results() -> None:
    picker = PyWebViewFolderPicker(folder_dialog_type="folder")
    assert picker.choose_directory() is None

    picker.attach(FakeWindow(["/tmp/selected"]))
    assert picker.choose_directory() == "/tmp/selected"

    picker.attach(FakeWindow(None))
    assert picker.choose_directory() is None
