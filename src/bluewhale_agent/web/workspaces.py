"""Workspace selection strategies for server and desktop modes."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from bluewhale_agent.desktop.grants import WorkspaceGrantError, WorkspaceGrantRegistry
from bluewhale_agent.web.schemas import RunCreateRequest


class WorkspaceSelectionError(ValueError):
    """Raised when an API-selected workspace violates its configured boundary."""


class WorkspaceResolver(Protocol):
    def resolve(self, request: RunCreateRequest) -> Path:
        """Resolve a validated request into its authorized local directory."""


class RootWorkspaceResolver:
    """Resolve paths beneath a server-configured root directory."""

    def __init__(self, root: Path) -> None:
        self._root = root.resolve(strict=True)
        if not self._root.is_dir():
            raise ValueError("workspace root must be a directory")

    def resolve(self, request: RunCreateRequest) -> Path:
        if request.workspace_grant_id is not None:
            raise WorkspaceSelectionError("Workspace grants are unavailable in server mode")
        selected = Path(request.workspace or ".")
        candidate = (
            selected.resolve(strict=False)
            if selected.is_absolute()
            else (self._root / selected).resolve(strict=False)
        )
        try:
            relative = candidate.relative_to(self._root)
        except ValueError as error:
            raise WorkspaceSelectionError(
                "Workspace must stay inside the configured root"
            ) from error
        if any(
            part in {".bluewhale", ".git"} or part == ".env" or part.startswith(".env.")
            for part in relative.parts
        ):
            raise WorkspaceSelectionError("Workspace is protected")
        if not candidate.is_dir():
            raise WorkspaceSelectionError("Workspace does not exist or is not a directory")
        return candidate


class GrantedWorkspaceResolver:
    """Resolve only opaque grants created by the desktop native picker."""

    def __init__(self, registry: WorkspaceGrantRegistry) -> None:
        self._registry = registry

    def resolve(self, request: RunCreateRequest) -> Path:
        if request.workspace is not None:
            raise WorkspaceSelectionError("Desktop mode does not accept path text")
        if request.workspace_grant_id is None:
            raise WorkspaceSelectionError("Select a workspace before starting a task")
        try:
            return self._registry.resolve(request.workspace_grant_id)
        except WorkspaceGrantError as error:
            raise WorkspaceSelectionError(str(error)) from error
