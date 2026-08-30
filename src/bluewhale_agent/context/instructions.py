"""Safe loading of repository-owned agent instructions."""

from __future__ import annotations

from pathlib import Path


class ProjectInstructionsError(ValueError):
    """Project instruction file is unsafe or cannot be consumed."""


def load_project_instructions(workspace: Path, *, max_bytes: int = 64_000) -> str:
    """Load a root AGENTS.md without following links outside the workspace."""

    path = workspace.resolve() / "AGENTS.md"
    if not path.exists() and not path.is_symlink():
        return ""
    if path.is_symlink():
        raise ProjectInstructionsError("AGENTS.md must not be a symbolic link")
    if not path.is_file():
        raise ProjectInstructionsError("AGENTS.md must be a regular file")
    if path.stat().st_size > max_bytes:
        raise ProjectInstructionsError("AGENTS.md is too large")
    try:
        return path.read_text(encoding="utf-8").strip()
    except UnicodeDecodeError as error:
        raise ProjectInstructionsError("AGENTS.md must be UTF-8 text") from error
