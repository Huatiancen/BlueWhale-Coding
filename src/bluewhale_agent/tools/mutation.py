"""Atomic, workspace-scoped text mutation tools."""

from __future__ import annotations

import hashlib
import os
import tempfile
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.tools.base import BaseTool, ToolContext, ToolExecutionError, ToolOutput


class WriteFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    content: str
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class ApplyPatchArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    search: str = Field(min_length=1)
    replace: str
    expected_sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")


class GetDiffArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")


def _read_before(path: Path) -> tuple[bytes | None, str | None]:
    if not path.exists():
        return None, None
    if not path.is_file():
        raise ToolExecutionError("Requested path is not a regular file")
    raw = path.read_bytes()
    try:
        return raw, raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("Existing file is not valid UTF-8 text") from exc


def _check_expected_hash(raw: bytes | None, expected: str | None) -> None:
    if expected is None:
        return
    actual = hashlib.sha256(raw or b"").hexdigest()
    if actual.lower() != expected.lower():
        raise ToolExecutionError(
            f"File hash conflict: expected {expected.lower()}, found {actual}"
        )


def _atomic_write(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary_name = tempfile.mkstemp(
        prefix=".bluewhale-", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            if path.exists():
                os.fchmod(handle.fileno(), path.stat().st_mode & 0o777)
            handle.write(content.encode("utf-8"))
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except (OSError, UnicodeEncodeError) as exc:
        temporary.unlink(missing_ok=True)
        raise ToolExecutionError(f"Atomic write failed: {exc}") from exc


def _prepare_target(context: ToolContext, requested: str) -> Path:
    unresolved = context.paths.root / Path(requested)
    if unresolved.is_symlink():
        raise ToolExecutionError("Symbolic-link mutation targets are not allowed")
    return context.paths.resolve(requested, must_exist=False)


class WriteFileTool(BaseTool):
    name = "write_file"
    description = "Atomically create or replace one UTF-8 workspace file."
    arguments_model = WriteFileArguments

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = cast(WriteFileArguments, arguments)
        path = _prepare_target(context, request.path)
        raw_before, before = _read_before(path)
        _check_expected_hash(raw_before, request.expected_sha256)
        _atomic_write(path, request.content)

        relative = path.relative_to(context.paths.root).as_posix()
        change = context.changeset.record(relative, before, request.content)
        return ToolOutput(
            summary=f"Wrote {relative}",
            metadata={
                "path": relative,
                "created": before is None,
                "before_sha256": change.before_sha256 if change is not None else None,
                "after_sha256": hashlib.sha256(request.content.encode("utf-8")).hexdigest(),
            },
        )


class ApplyPatchTool(BaseTool):
    name = "apply_patch"
    description = "Atomically replace one uniquely matching fragment in a UTF-8 workspace file."
    arguments_model = ApplyPatchArguments

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = cast(ApplyPatchArguments, arguments)
        path = _prepare_target(context, request.path)
        raw_before, before = _read_before(path)
        if before is None:
            raise ToolExecutionError(f"Patch target does not exist: {request.path}")
        _check_expected_hash(raw_before, request.expected_sha256)

        occurrences = before.count(request.search)
        if occurrences == 0:
            raise ToolExecutionError("Patch search fragment was not found")
        if occurrences > 1:
            raise ToolExecutionError("Patch search fragment has multiple matches")

        after = before.replace(request.search, request.replace, 1)
        _atomic_write(path, after)
        relative = path.relative_to(context.paths.root).as_posix()
        change = context.changeset.record(relative, before, after)
        return ToolOutput(
            summary=f"Patched {relative}",
            metadata={
                "path": relative,
                "replacements": 1,
                "before_sha256": change.before_sha256 if change is not None else None,
                "after_sha256": hashlib.sha256(after.encode("utf-8")).hexdigest(),
            },
        )


class GetDiffTool(BaseTool):
    name = "get_diff"
    description = "Return the unified diff for changes made during this agent run."
    arguments_model = GetDiffArguments

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        diff = context.changeset.get_diff()
        return ToolOutput(
            summary=f"Generated diff for {len(context.changeset.changes)} files",
            content=diff,
            metadata={"changed_files": len(context.changeset.changes)},
        )
