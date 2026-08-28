from __future__ import annotations

from pathlib import Path

import pytest

from bluewhale_agent.desktop.grants import WorkspaceGrantError, WorkspaceGrantRegistry


def test_registry_grants_and_resolves_canonical_directory(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = WorkspaceGrantRegistry()

    grant = registry.grant(project)

    assert grant.path == project.resolve()
    assert grant.display_name == "project"
    assert len(grant.id) >= 32
    assert registry.resolve(grant.id) == project.resolve()


def test_new_grant_replaces_previous_grant(tmp_path: Path) -> None:
    first = tmp_path / "first"
    second = tmp_path / "second"
    first.mkdir()
    second.mkdir()
    registry = WorkspaceGrantRegistry()
    old = registry.grant(first)

    current = registry.grant(second)

    assert registry.current() == current
    with pytest.raises(WorkspaceGrantError, match="Unknown workspace grant"):
        registry.resolve(old.id)


def test_registry_rejects_unknown_removed_and_non_directory_grants(tmp_path: Path) -> None:
    registry = WorkspaceGrantRegistry()
    with pytest.raises(WorkspaceGrantError, match="Unknown workspace grant"):
        registry.resolve("forged-grant")

    project = tmp_path / "project"
    project.mkdir()
    grant = registry.grant(project)
    project.rmdir()
    with pytest.raises(WorkspaceGrantError, match="no longer available"):
        registry.resolve(grant.id)

    file_path = tmp_path / "file.txt"
    file_path.write_text("not a directory", encoding="utf-8")
    with pytest.raises(WorkspaceGrantError, match="not a directory"):
        registry.grant(file_path)
    with pytest.raises(WorkspaceGrantError, match="does not exist"):
        registry.grant(tmp_path / "missing")


def test_registry_clear_removes_current_grant(tmp_path: Path) -> None:
    registry = WorkspaceGrantRegistry()
    registry.grant(tmp_path)

    registry.clear()

    assert registry.current() is None
