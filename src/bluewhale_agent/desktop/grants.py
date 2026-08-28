"""Process-local workspace grants created by native folder selection."""

from __future__ import annotations

import hmac
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path


@dataclass(frozen=True, slots=True)
class WorkspaceGrant:
    """An opaque authorization for one canonical local directory."""

    id: str
    path: Path
    display_name: str
    granted_at: datetime


class WorkspaceGrantError(ValueError):
    """Raised when a workspace cannot be granted or resolved."""


class WorkspaceGrantRegistry:
    """Keep only the workspace explicitly selected for this app process."""

    def __init__(self) -> None:
        self._current: WorkspaceGrant | None = None

    def grant(self, selected: str | Path) -> WorkspaceGrant:
        try:
            path = Path(selected).resolve(strict=True)
        except (OSError, RuntimeError) as error:
            raise WorkspaceGrantError("Workspace does not exist") from error
        if not path.is_dir():
            raise WorkspaceGrantError("Workspace is not a directory")
        grant = WorkspaceGrant(
            id=secrets.token_urlsafe(32),
            path=path,
            display_name=path.name or str(path),
            granted_at=datetime.now(UTC),
        )
        self._current = grant
        return grant

    def current(self) -> WorkspaceGrant | None:
        return self._current

    def resolve(self, grant_id: str) -> Path:
        grant = self._current
        if grant is None or not hmac.compare_digest(grant.id, grant_id):
            raise WorkspaceGrantError("Unknown workspace grant")
        if not grant.path.is_dir():
            raise WorkspaceGrantError("Granted workspace is no longer available")
        return grant.path

    def clear(self) -> None:
        self._current = None
