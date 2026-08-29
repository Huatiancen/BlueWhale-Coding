"""In-memory tracking and diff generation for one agent run."""

from __future__ import annotations

import difflib
import hashlib

from pydantic import BaseModel, ConfigDict


def text_sha256(content: str) -> str:
    """Return the SHA-256 digest of UTF-8 text."""

    return hashlib.sha256(content.encode("utf-8")).hexdigest()


class FileChange(BaseModel):
    """The original and latest state of one changed workspace file."""

    model_config = ConfigDict(frozen=True)

    path: str
    before: str | None
    after: str
    before_sha256: str | None
    after_sha256: str


class FileChangeSummary(BaseModel):
    """Serializable presentation data for one completed file change."""

    model_config = ConfigDict(frozen=True)

    path: str
    created: bool
    additions: int
    deletions: int
    before_sha256: str | None
    after_sha256: str
    before: str | None = None
    after: str
    diff: str


class ChangeSetSnapshot(BaseModel):
    """Immutable change summary persisted with a completed agent turn."""

    model_config = ConfigDict(frozen=True)

    files: tuple[FileChangeSummary, ...]
    additions: int
    deletions: int
    diff: str


class ChangeSet:
    """Track net text changes without depending on a Git repository."""

    def __init__(self) -> None:
        self._changes: dict[str, FileChange] = {}

    @property
    def changes(self) -> tuple[FileChange, ...]:
        return tuple(self._changes[path] for path in sorted(self._changes))

    def get(self, path: str) -> FileChange | None:
        return self._changes.get(path)

    def record(self, path: str, before: str | None, after: str) -> FileChange | None:
        """Record a successful write, preserving the first observed state."""

        previous = self._changes.get(path)
        original = previous.before if previous is not None else before
        if original is not None and original == after:
            self._changes.pop(path, None)
            return None

        change = FileChange(
            path=path,
            before=original,
            after=after,
            before_sha256=text_sha256(original) if original is not None else None,
            after_sha256=text_sha256(after),
        )
        self._changes[path] = change
        return change

    def get_diff(self) -> str:
        """Return a unified diff for all net changes in stable path order."""

        chunks: list[str] = []
        for change in self.changes:
            before = "" if change.before is None else change.before
            from_file = "/dev/null" if change.before is None else f"a/{change.path}"
            diff_lines = list(
                difflib.unified_diff(
                    before.splitlines(keepends=True),
                    change.after.splitlines(keepends=True),
                    fromfile=from_file,
                    tofile=f"b/{change.path}",
                    lineterm="\n",
                )
            )
            if not diff_lines and change.before is None:
                diff_lines = [f"--- {from_file}\n", f"+++ b/{change.path}\n"]
            chunks.extend(line if line.endswith("\n") else f"{line}\n" for line in diff_lines)
        return "".join(chunks)

    def snapshot(self) -> ChangeSetSnapshot:
        """Build a stable, GUI-ready representation of the current net changes."""

        files: list[FileChangeSummary] = []
        for change in self.changes:
            additions, deletions = _line_counts(change.before, change.after)
            files.append(
                FileChangeSummary(
                    path=change.path,
                    created=change.before is None,
                    additions=additions,
                    deletions=deletions,
                    before_sha256=change.before_sha256,
                    after_sha256=change.after_sha256,
                    before=change.before,
                    after=change.after,
                    diff=_change_diff(change),
                )
            )
        return ChangeSetSnapshot(
            files=tuple(files),
            additions=sum(item.additions for item in files),
            deletions=sum(item.deletions for item in files),
            diff=self.get_diff(),
        )


def _line_counts(before: str | None, after: str) -> tuple[int, int]:
    matcher = difflib.SequenceMatcher(
        a=[] if before is None else before.splitlines(),
        b=after.splitlines(),
        autojunk=False,
    )
    additions = 0
    deletions = 0
    for tag, before_start, before_end, after_start, after_end in matcher.get_opcodes():
        if tag in {"insert", "replace"}:
            additions += after_end - after_start
        if tag in {"delete", "replace"}:
            deletions += before_end - before_start
    return additions, deletions


def _change_diff(change: FileChange) -> str:
    before = "" if change.before is None else change.before
    lines = difflib.unified_diff(
        before.splitlines(keepends=True),
        change.after.splitlines(keepends=True),
        fromfile="/dev/null" if change.before is None else f"a/{change.path}",
        tofile=f"b/{change.path}",
        lineterm="\n",
    )
    result = "".join(line if line.endswith("\n") else f"{line}\n" for line in lines)
    if not result and change.before is None:
        return f"--- /dev/null\n+++ b/{change.path}\n"
    return result
