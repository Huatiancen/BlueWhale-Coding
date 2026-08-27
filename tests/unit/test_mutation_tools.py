import hashlib
from pathlib import Path

import pytest

from bluewhale_agent.domain.models import Action
from bluewhale_agent.runtime.changeset import ChangeSet
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.runtime.permissions import PermissionDecision, PermissionPolicy
from bluewhale_agent.tools import mutation
from bluewhale_agent.tools.base import ToolContext, ToolExecutionError
from bluewhale_agent.tools.mutation import ApplyPatchTool, GetDiffTool, WriteFileTool


def make_context(tmp_path: Path) -> ToolContext:
    return ToolContext(paths=WorkspacePaths(tmp_path), changeset=ChangeSet())


@pytest.mark.asyncio
async def test_write_file_creates_file_and_records_hashes(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    result = await WriteFileTool().invoke(
        {"path": "src/app.py", "content": "print('hello')\n"}, context
    )

    created = tmp_path / "src" / "app.py"
    assert created.read_text(encoding="utf-8") == "print('hello')\n"
    assert result.metadata["created"] is True
    change = context.changeset.get("src/app.py")
    assert change is not None
    assert change.before is None
    assert change.after_sha256 == hashlib.sha256(created.read_bytes()).hexdigest()


@pytest.mark.asyncio
async def test_apply_patch_replaces_one_unique_fragment(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("def total():\n    return 1\n", encoding="utf-8")
    context = make_context(tmp_path)

    result = await ApplyPatchTool().invoke(
        {"path": "app.py", "search": "return 1", "replace": "return 2"}, context
    )

    assert target.read_text(encoding="utf-8") == "def total():\n    return 2\n"
    assert result.metadata["replacements"] == 1
    assert context.changeset.get("app.py") is not None


@pytest.mark.asyncio
async def test_apply_patch_rejects_missing_target_without_changes(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    with pytest.raises(ToolExecutionError, match="does not exist"):
        await ApplyPatchTool().invoke(
            {"path": "missing.py", "search": "old", "replace": "new"}, context
        )

    assert not (tmp_path / "missing.py").exists()
    assert context.changeset.changes == ()


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("initial", "search", "message"),
    [
        ("alpha\n", "missing", "not found"),
        ("same\nsame\n", "same", "multiple"),
    ],
)
async def test_apply_patch_rejects_non_unique_search_without_changes(
    tmp_path: Path,
    initial: str,
    search: str,
    message: str,
) -> None:
    target = tmp_path / "app.py"
    target.write_text(initial, encoding="utf-8")
    context = make_context(tmp_path)

    with pytest.raises(ToolExecutionError, match=message):
        await ApplyPatchTool().invoke(
            {"path": "app.py", "search": search, "replace": "new"}, context
        )

    assert target.read_text(encoding="utf-8") == initial
    assert context.changeset.changes == ()


@pytest.mark.asyncio
async def test_write_file_rejects_stale_hash_without_changes(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("current\n", encoding="utf-8")
    context = make_context(tmp_path)

    with pytest.raises(ToolExecutionError, match="hash conflict"):
        await WriteFileTool().invoke(
            {
                "path": "app.py",
                "content": "replacement\n",
                "expected_sha256": "0" * 64,
            },
            context,
        )

    assert target.read_text(encoding="utf-8") == "current\n"
    assert context.changeset.changes == ()


@pytest.mark.asyncio
async def test_apply_patch_rejects_non_utf8_file_without_changes(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    original = b"valid\xffinvalid"
    target.write_bytes(original)
    context = make_context(tmp_path)

    with pytest.raises(ToolExecutionError, match="UTF-8"):
        await ApplyPatchTool().invoke(
            {"path": "app.py", "search": "valid", "replace": "new"}, context
        )

    assert target.read_bytes() == original
    assert context.changeset.changes == ()


@pytest.mark.asyncio
async def test_write_file_rejects_unencodable_content_without_changes(tmp_path: Path) -> None:
    context = make_context(tmp_path)

    with pytest.raises(ToolExecutionError, match="Atomic write failed"):
        await WriteFileTool().invoke(
            {"path": "app.py", "content": "invalid surrogate: \ud800"}, context
        )

    assert not (tmp_path / "app.py").exists()
    assert context.changeset.changes == ()
    assert list(tmp_path.glob(".bluewhale-*.tmp")) == []


@pytest.mark.asyncio
async def test_atomic_replace_failure_preserves_file_and_changeset(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    target = tmp_path / "app.py"
    target.write_text("before\n", encoding="utf-8")
    context = make_context(tmp_path)

    def fail_replace(source: Path, destination: Path) -> None:
        raise OSError("replace failed")

    monkeypatch.setattr(mutation.os, "replace", fail_replace)

    with pytest.raises(ToolExecutionError, match="replace failed"):
        await WriteFileTool().invoke(
            {"path": "app.py", "content": "after\n"}, context
        )

    assert target.read_text(encoding="utf-8") == "before\n"
    assert context.changeset.changes == ()
    assert list(tmp_path.glob(".bluewhale-*.tmp")) == []


@pytest.mark.asyncio
async def test_get_diff_is_git_independent_and_keeps_original_before(tmp_path: Path) -> None:
    target = tmp_path / "app.py"
    target.write_text("one\n", encoding="utf-8")
    context = make_context(tmp_path)
    writer = WriteFileTool()

    await writer.invoke({"path": "app.py", "content": "two\n"}, context)
    await writer.invoke({"path": "app.py", "content": "three\n"}, context)
    result = await GetDiffTool().invoke({}, context)

    assert "--- a/app.py" in result.content
    assert "+++ b/app.py" in result.content
    assert "-one" in result.content
    assert "+three" in result.content
    assert "+two" not in result.content
    change = context.changeset.get("app.py")
    assert change is not None
    assert change.before == "one\n"


def test_get_diff_keeps_lines_separate_without_terminal_newline() -> None:
    changeset = ChangeSet()
    changeset.record("app.py", "before", "after")

    diff = changeset.get_diff()

    assert "-before\n+after\n" in diff


def test_get_diff_includes_empty_created_file() -> None:
    changeset = ChangeSet()
    changeset.record("empty.txt", None, "")

    diff = changeset.get_diff()

    assert "--- /dev/null" in diff
    assert "+++ b/empty.txt" in diff


def test_permission_policy_asks_only_before_overwriting_with_write_file(tmp_path: Path) -> None:
    (tmp_path / "existing.py").write_text("old\n", encoding="utf-8")
    policy = PermissionPolicy(paths=WorkspacePaths(tmp_path))

    overwrite = policy.evaluate(
        Action(
            id="1",
            tool_name="write_file",
            arguments={"path": "existing.py", "content": "new\n"},
        )
    )
    create = policy.evaluate(
        Action(
            id="2",
            tool_name="write_file",
            arguments={"path": "new.py", "content": "new\n"},
        )
    )
    patch = policy.evaluate(
        Action(id="3", tool_name="apply_patch", arguments={"path": "existing.py"})
    )

    assert overwrite.decision is PermissionDecision.ASK
    assert create.decision is PermissionDecision.ALLOW
    assert patch.decision is PermissionDecision.ALLOW
