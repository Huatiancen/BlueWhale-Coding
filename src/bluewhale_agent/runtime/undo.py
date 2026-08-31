"""Conflict-aware rollback for a persisted change set."""

from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path

from bluewhale_agent.runtime.changeset import ChangeSetSnapshot, FileChangeSummary, text_sha256
from bluewhale_agent.runtime.paths import PathAccessError, WorkspacePaths


class ChangeSetUndoError(RuntimeError):
    """Raised when a change set cannot be safely reverted."""


@dataclass(frozen=True, slots=True)
class _UndoTarget:
    path: Path
    change: FileChangeSummary


def undo_changeset(workspace: Path, snapshot: ChangeSetSnapshot) -> tuple[str, ...]:
    """Restore a snapshot only when every file still matches its recorded result."""

    return undo_files(workspace, snapshot, tuple(item.path for item in snapshot.files))


def undo_files(
    workspace: Path,
    snapshot: ChangeSetSnapshot,
    selected_paths: tuple[str, ...],
) -> tuple[str, ...]:
    """Restore selected snapshot files after validating the whole selection."""

    if not selected_paths:
        raise ChangeSetUndoError("Select at least one file to undo")
    requested = set(selected_paths)
    if len(requested) != len(selected_paths):
        raise ChangeSetUndoError("Each file may be selected only once")
    available = {change.path: change for change in snapshot.files}
    missing = sorted(requested - set(available))
    if missing:
        raise ChangeSetUndoError(f"{missing[0]} is not part of this change set")

    paths = WorkspacePaths(workspace)
    targets = tuple(
        _prepare_target(paths, change)
        for change in snapshot.files
        if change.path in requested
    )
    for target in targets:
        _validate_current_content(target)

    for target in targets:
        if target.change.created:
            target.path.unlink()
        else:
            assert target.change.before is not None
            _atomic_write(target.path, target.change.before)
    return tuple(target.change.path for target in targets)


def _prepare_target(paths: WorkspacePaths, change: FileChangeSummary) -> _UndoTarget:
    unresolved = paths.root / Path(change.path)
    if unresolved.is_symlink():
        raise ChangeSetUndoError(f"Cannot undo {change.path}: symbolic links are not allowed")
    try:
        resolved = paths.resolve(change.path)
    except PathAccessError as error:
        raise ChangeSetUndoError(f"Cannot undo {change.path}: {error}") from error
    if not resolved.is_file() or resolved.is_symlink():
        raise ChangeSetUndoError(f"Cannot undo {change.path}: target is not a regular file")
    if not change.created and change.before is None:
        raise ChangeSetUndoError(
            f"Cannot undo {change.path}: this history record does not contain rollback data"
        )
    return _UndoTarget(path=resolved, change=change)


def _validate_current_content(target: _UndoTarget) -> None:
    try:
        current = target.path.read_text(encoding="utf-8")
    except UnicodeDecodeError as error:
        raise ChangeSetUndoError(
            f"Cannot undo {target.change.path}: current file is not UTF-8 text"
        ) from error
    except OSError as error:
        raise ChangeSetUndoError(f"Cannot undo {target.change.path}: {error}") from error
    if text_sha256(current) != target.change.after_sha256:
        raise ChangeSetUndoError(
            f"Cannot undo {target.change.path}: file changed after this change set was recorded"
        )


def _atomic_write(path: Path, content: str) -> None:
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".bluewhale-undo-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            os.fchmod(handle.fileno(), path.stat().st_mode & 0o777)
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, UnicodeEncodeError) as error:
        temporary.unlink(missing_ok=True)
        raise ChangeSetUndoError(f"Cannot restore {path.name}: {error}") from error
