"""Compact, deterministic index of a coding workspace."""

from __future__ import annotations

import ast
from datetime import UTC, datetime
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.runtime.paths import WorkspacePaths

_MANIFEST_PRIORITY = {
    "pyproject.toml": 0,
    "package.json": 1,
    "Cargo.toml": 2,
    "go.mod": 3,
}
_LANGUAGES = {
    ".c": "c",
    ".cpp": "cpp",
    ".css": "css",
    ".go": "go",
    ".html": "html",
    ".java": "java",
    ".js": "javascript",
    ".json": "json",
    ".jsx": "javascript",
    ".md": "markdown",
    ".py": "python",
    ".rs": "rust",
    ".toml": "toml",
    ".ts": "typescript",
    ".tsx": "typescript",
    ".yaml": "yaml",
    ".yml": "yaml",
}


class WorkspaceEntry(BaseModel):
    """One file represented in the workspace map."""

    model_config = ConfigDict(frozen=True)

    path: str = Field(min_length=1)
    language: str = Field(min_length=1)
    size_bytes: int = Field(ge=0)
    modified_at: float = Field(ge=0)
    symbols: tuple[str, ...] = ()


class WorkspaceMap(BaseModel):
    """Stable collection of compact workspace entries."""

    model_config = ConfigDict(frozen=True)

    entries: tuple[WorkspaceEntry, ...]

    def render(self) -> str:
        lines = ["# Workspace map"]
        for entry in self.entries:
            modified = datetime.fromtimestamp(entry.modified_at, UTC).isoformat()
            lines.append(
                f"- {entry.path} [{entry.language}, {entry.size_bytes} bytes, "
                f"modified={modified}]"
            )
            lines.extend(f"  - {symbol}" for symbol in entry.symbols)
        return "\n".join(lines)


class WorkspaceMapBuilder:
    """Build a lightweight map without embedding complete source files."""

    def __init__(self, paths: WorkspacePaths, *, max_python_bytes: int = 1_048_576) -> None:
        self._paths = paths
        self._max_python_bytes = max_python_bytes

    def build(self) -> WorkspaceMap:
        entries = [self._entry(path) for path in self._paths.iter_files(".")]
        entries.sort(key=lambda entry: (_MANIFEST_PRIORITY.get(entry.path, 100), entry.path))
        return WorkspaceMap(entries=tuple(entries))

    def _entry(self, path: Path) -> WorkspaceEntry:
        stat = path.stat()
        relative = path.relative_to(self._paths.root).as_posix()
        language = self._language(path)
        symbols = self._python_symbols(path) if language == "python" else ()
        return WorkspaceEntry(
            path=relative,
            language=language,
            size_bytes=stat.st_size,
            modified_at=stat.st_mtime,
            symbols=symbols,
        )

    @staticmethod
    def _language(path: Path) -> str:
        if path.name == "go.mod":
            return "go-module"
        return _LANGUAGES.get(path.suffix.lower(), "text")

    def _python_symbols(self, path: Path) -> tuple[str, ...]:
        if path.stat().st_size > self._max_python_bytes:
            return ()
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, SyntaxError, UnicodeDecodeError):
            return ()

        symbols: list[str] = []
        for node in tree.body:
            if isinstance(node, ast.ClassDef):
                symbols.append(self._class_signature(node))
            elif isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(self._function_signature(node))
        return tuple(symbols)

    @staticmethod
    def _class_signature(node: ast.ClassDef) -> str:
        parents = [ast.unparse(base) for base in node.bases]
        parents.extend(
            f"{keyword.arg}={ast.unparse(keyword.value)}"
            for keyword in node.keywords
            if keyword.arg is not None
        )
        suffix = f"({', '.join(parents)})" if parents else ""
        return f"class {node.name}{suffix}"

    @classmethod
    def _function_signature(cls, node: ast.FunctionDef | ast.AsyncFunctionDef) -> str:
        prefix = "async def" if isinstance(node, ast.AsyncFunctionDef) else "def"
        arguments = cls._format_arguments(node.args)
        returns = f" -> {ast.unparse(node.returns)}" if node.returns is not None else ""
        return f"{prefix} {node.name}({arguments}){returns}"

    @classmethod
    def _format_arguments(cls, arguments: ast.arguments) -> str:
        rendered: list[str] = []
        positional = [*arguments.posonlyargs, *arguments.args]
        default_offset = len(positional) - len(arguments.defaults)
        for index, argument in enumerate(positional):
            default = (
                arguments.defaults[index - default_offset]
                if index >= default_offset
                else None
            )
            rendered.append(cls._format_argument(argument, default))
            if arguments.posonlyargs and index + 1 == len(arguments.posonlyargs):
                rendered.append("/")

        if arguments.vararg is not None:
            rendered.append(f"*{cls._format_argument(arguments.vararg)}")
        elif arguments.kwonlyargs:
            rendered.append("*")

        for argument, default in zip(
            arguments.kwonlyargs, arguments.kw_defaults, strict=True
        ):
            rendered.append(cls._format_argument(argument, default))
        if arguments.kwarg is not None:
            rendered.append(f"**{cls._format_argument(arguments.kwarg)}")
        return ", ".join(rendered)

    @staticmethod
    def _format_argument(argument: ast.arg, default: ast.expr | None = None) -> str:
        rendered = argument.arg
        if argument.annotation is not None:
            rendered += f": {ast.unparse(argument.annotation)}"
        if default is not None:
            rendered += f" = {ast.unparse(default)}"
        return rendered
