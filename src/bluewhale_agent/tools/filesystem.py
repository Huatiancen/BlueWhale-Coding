"""Read-only filesystem tools implemented inside the local runtime."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bluewhale_agent.tools.base import BaseTool, ToolContext, ToolExecutionError, ToolOutput


class ListFilesArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = "."


class ReadFileArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    path: str = Field(min_length=1)
    start_line: int = Field(default=1, ge=1)
    end_line: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_line_range(self) -> ReadFileArguments:
        if self.end_line is not None and self.end_line < self.start_line:
            raise ValueError("end_line must be greater than or equal to start_line")
        return self


class SearchTextArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    query: str = Field(min_length=1)
    path: str = "."
    regex: bool = False
    max_results: int = Field(default=50, ge=1, le=200)


def _read_text(path: Path, max_file_bytes: int) -> str:
    if not path.is_file():
        raise ToolExecutionError("Requested path is not a file")
    if path.stat().st_size > max_file_bytes:
        raise ToolExecutionError("File exceeds the configured size limit")
    raw = path.read_bytes()
    if b"\x00" in raw:
        raise ToolExecutionError("Binary files cannot be read")
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise ToolExecutionError("File is not valid UTF-8 text") from exc


class ListFilesTool(BaseTool):
    name = "list_files"
    description = "List readable files below a workspace-relative path."
    arguments_model = ListFilesArguments

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = cast(ListFilesArguments, arguments)
        files = context.paths.iter_files(request.path)
        relative = [path.relative_to(context.paths.root).as_posix() for path in files]
        return ToolOutput(
            summary=f"Listed {len(relative)} files",
            content=json.dumps(relative, ensure_ascii=False),
            metadata={"count": len(relative)},
        )


class ReadFileTool(BaseTool):
    name = "read_file"
    description = "Read a numbered line range from one UTF-8 workspace file."
    arguments_model = ReadFileArguments

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = cast(ReadFileArguments, arguments)
        path = context.paths.resolve(request.path)
        lines = _read_text(path, context.max_file_bytes).splitlines()
        requested_end = request.end_line or len(lines)
        bounded_end = min(requested_end, request.start_line + context.max_read_lines - 1)
        selected = lines[request.start_line - 1 : bounded_end]
        numbered = "\n".join(
            f"{number}: {line}" for number, line in enumerate(selected, request.start_line)
        )
        actual_end = request.start_line + len(selected) - 1 if selected else request.start_line - 1
        truncated = requested_end > bounded_end
        return ToolOutput(
            summary=f"Read {len(selected)} lines from {request.path}",
            content=numbered,
            metadata={
                "path": path.relative_to(context.paths.root).as_posix(),
                "start_line": request.start_line,
                "end_line": actual_end,
                "total_lines": len(lines),
                "truncated": truncated,
            },
        )


class SearchTextTool(BaseTool):
    name = "search_text"
    description = "Search UTF-8 workspace files using literal text or a regular expression."
    arguments_model = SearchTextArguments

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        request = cast(SearchTextArguments, arguments)
        expression = request.query if request.regex else re.escape(request.query)
        try:
            pattern = re.compile(expression)
        except re.error as exc:
            raise ToolExecutionError(f"Invalid regular expression: {exc}") from exc

        matches: list[dict[str, object]] = []
        truncated = False
        for path in context.paths.iter_files(request.path):
            try:
                lines = _read_text(path, context.max_file_bytes).splitlines()
            except ToolExecutionError:
                continue
            for line_number, line in enumerate(lines, 1):
                if pattern.search(line) is None:
                    continue
                if len(matches) == request.max_results:
                    truncated = True
                    break
                matches.append(
                    {
                        "path": path.relative_to(context.paths.root).as_posix(),
                        "line": line_number,
                        "text": line,
                    }
                )
            if truncated:
                break

        return ToolOutput(
            summary=f"Found {len(matches)} matches",
            content=json.dumps(matches, ensure_ascii=False),
            metadata={"count": len(matches), "truncated": truncated},
        )
