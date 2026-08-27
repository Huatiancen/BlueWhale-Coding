import json
from pathlib import Path

import pytest

from bluewhale_agent.domain.models import Action, ObservationStatus
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.runtime.permissions import PermissionPolicy
from bluewhale_agent.tools.base import ToolContext
from bluewhale_agent.tools.filesystem import ListFilesTool, ReadFileTool, SearchTextTool
from bluewhale_agent.tools.registry import ToolRegistry


def make_registry(tmp_path: Path, *, max_file_bytes: int = 1024) -> ToolRegistry:
    context = ToolContext(
        paths=WorkspacePaths(tmp_path),
        max_file_bytes=max_file_bytes,
        max_read_lines=100,
    )
    return ToolRegistry(
        tools=[ListFilesTool(), ReadFileTool(), SearchTextTool()],
        context=context,
        permission_policy=PermissionPolicy(),
    )


@pytest.mark.asyncio
async def test_list_files_returns_sorted_relative_paths_and_skips_ignored(tmp_path: Path) -> None:
    (tmp_path / "z.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / "a.py").write_text("pass\n", encoding="utf-8")
    (tmp_path / ".git").mkdir()
    (tmp_path / ".git" / "config").write_text("secret\n", encoding="utf-8")
    (tmp_path / ".env").write_text("API_KEY=secret\n", encoding="utf-8")

    result = await make_registry(tmp_path).dispatch(
        Action(id="call-1", tool_name="list_files", arguments={})
    )

    assert result.status is ObservationStatus.SUCCESS
    assert json.loads(result.content) == ["a.py", "z.py"]


@pytest.mark.asyncio
async def test_read_file_returns_requested_numbered_lines(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("alpha\nbeta\ngamma\ndelta\n", encoding="utf-8")

    result = await make_registry(tmp_path).dispatch(
        Action(
            id="call-1",
            tool_name="read_file",
            arguments={"path": "app.py", "start_line": 2, "end_line": 3},
        )
    )

    assert result.status is ObservationStatus.SUCCESS
    assert result.content == "2: beta\n3: gamma"
    assert result.metadata["total_lines"] == 4


@pytest.mark.asyncio
async def test_read_file_rejects_binary_content(tmp_path: Path) -> None:
    (tmp_path / "image.bin").write_bytes(b"image\x00data")

    result = await make_registry(tmp_path).dispatch(
        Action(id="call-1", tool_name="read_file", arguments={"path": "image.bin"})
    )

    assert result.status is ObservationStatus.ERROR
    assert "binary" in result.summary.lower()


@pytest.mark.asyncio
async def test_read_file_rejects_files_over_size_limit(tmp_path: Path) -> None:
    (tmp_path / "large.txt").write_text("x" * 20, encoding="utf-8")

    result = await make_registry(tmp_path, max_file_bytes=10).dispatch(
        Action(id="call-1", tool_name="read_file", arguments={"path": "large.txt"})
    )

    assert result.status is ObservationStatus.ERROR
    assert "size limit" in result.summary.lower()


@pytest.mark.asyncio
async def test_search_text_supports_literal_and_regular_expression(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("def divide(a, b):\n    return a / b\n", encoding="utf-8")
    registry = make_registry(tmp_path)

    literal = await registry.dispatch(
        Action(id="call-1", tool_name="search_text", arguments={"query": "return a / b"})
    )
    regex = await registry.dispatch(
        Action(
            id="call-2",
            tool_name="search_text",
            arguments={"query": r"def\s+divide", "regex": True},
        )
    )

    assert json.loads(literal.content)[0]["line"] == 2
    assert json.loads(regex.content)[0]["path"] == "app.py"


@pytest.mark.asyncio
async def test_search_text_stops_at_result_limit(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("hit\nhit\nhit\n", encoding="utf-8")

    result = await make_registry(tmp_path).dispatch(
        Action(
            id="call-1",
            tool_name="search_text",
            arguments={"query": "hit", "max_results": 2},
        )
    )

    assert len(json.loads(result.content)) == 2
    assert result.metadata["truncated"] is True


@pytest.mark.asyncio
async def test_registry_rejects_unknown_tool_and_extra_arguments(tmp_path: Path) -> None:
    registry = make_registry(tmp_path)

    unknown = await registry.dispatch(Action(id="call-1", tool_name="unknown", arguments={}))
    invalid = await registry.dispatch(
        Action(
            id="call-2",
            tool_name="read_file",
            arguments={"path": "missing.py", "unexpected": True},
        )
    )

    assert unknown.status is ObservationStatus.ERROR
    assert "Unknown tool" in unknown.summary
    assert invalid.status is ObservationStatus.ERROR
    assert "Invalid arguments" in invalid.summary


@pytest.mark.asyncio
async def test_registry_denies_workspace_escape(tmp_path: Path) -> None:
    result = await make_registry(tmp_path).dispatch(
        Action(id="call-1", tool_name="read_file", arguments={"path": "../secret.txt"})
    )

    assert result.status is ObservationStatus.DENIED
    assert "outside the workspace" in result.summary


def test_registry_exposes_strict_function_schemas(tmp_path: Path) -> None:
    schemas = make_registry(tmp_path).schemas()
    read_schema = next(item for item in schemas if item["function"]["name"] == "read_file")

    assert read_schema["type"] == "function"
    assert read_schema["function"]["parameters"]["additionalProperties"] is False
