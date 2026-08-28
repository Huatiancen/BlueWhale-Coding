from __future__ import annotations

from pathlib import Path

import pytest

from bluewhale_agent.desktop.grants import WorkspaceGrantRegistry
from bluewhale_agent.web.schemas import RunCreateRequest
from bluewhale_agent.web.workspaces import (
    GrantedWorkspaceResolver,
    RootWorkspaceResolver,
    WorkspaceSelectionError,
)


def test_root_resolver_preserves_server_mode_boundaries(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    resolver = RootWorkspaceResolver(tmp_path)

    assert resolver.resolve(RunCreateRequest(task="Inspect", workspace="project")) == project
    assert resolver.resolve(RunCreateRequest(task="Inspect")) == tmp_path

    with pytest.raises(WorkspaceSelectionError, match="configured root"):
        resolver.resolve(RunCreateRequest(task="Escape", workspace=".."))
    with pytest.raises(WorkspaceSelectionError, match="unavailable in server mode"):
        resolver.resolve(RunCreateRequest(task="Inspect", workspace_grant_id="grant"))


def test_granted_resolver_never_trusts_path_text(tmp_path: Path) -> None:
    project = tmp_path / "project"
    project.mkdir()
    registry = WorkspaceGrantRegistry()
    grant = registry.grant(project)
    resolver = GrantedWorkspaceResolver(registry)

    request = RunCreateRequest(task="Inspect", workspace_grant_id=grant.id)
    assert resolver.resolve(request) == project.resolve()

    with pytest.raises(WorkspaceSelectionError, match="does not accept path text"):
        resolver.resolve(
            RunCreateRequest(task="Escape", workspace="/", workspace_grant_id=grant.id)
        )
    with pytest.raises(WorkspaceSelectionError, match="Select a workspace"):
        resolver.resolve(RunCreateRequest(task="Inspect"))


def test_root_resolver_rejects_protected_and_missing_directories(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    resolver = RootWorkspaceResolver(tmp_path)

    with pytest.raises(WorkspaceSelectionError, match="protected"):
        resolver.resolve(RunCreateRequest(task="Inspect", workspace=".git"))
    with pytest.raises(WorkspaceSelectionError, match="does not exist"):
        resolver.resolve(RunCreateRequest(task="Inspect", workspace="missing"))
