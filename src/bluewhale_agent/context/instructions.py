"""Safe loading of repository-owned agent instructions."""

from __future__ import annotations

from pathlib import Path

from pydantic import BaseModel, ConfigDict

from bluewhale_agent.runtime.paths import PathAccessError, WorkspacePaths


class ProjectInstructionsError(ValueError):
    """Project instruction file is unsafe or cannot be consumed."""


class InstructionDocument(BaseModel):
    model_config = ConfigDict(frozen=True)

    source: str
    scope: str
    content: str

    @property
    def summary(self) -> str:
        first = next((line.strip() for line in self.content.splitlines() if line.strip()), "")
        return first if len(first) <= 120 else f"{first[:117]}..."


class InstructionBundle(BaseModel):
    model_config = ConfigDict(frozen=True)

    documents: tuple[InstructionDocument, ...] = ()

    def render(self) -> str:
        sections: list[str] = []
        for document in self.documents:
            sections.append(
                f"## {document.source} (scope: {document.scope})\n{document.content}"
            )
        return "\n\n".join(sections)


class InstructionResolver:
    """Resolve every AGENTS.md whose directory contains a target path."""

    def __init__(self, workspace: Path, *, max_bytes: int = 64_000) -> None:
        self._paths = WorkspacePaths(workspace)
        self._max_bytes = max_bytes

    def resolve_for(self, target: str | Path) -> InstructionBundle:
        try:
            resolved = self._paths.resolve(Path(target).as_posix(), must_exist=False)
        except PathAccessError as error:
            raise ProjectInstructionsError("Instruction target is outside workspace") from error
        directory = resolved if resolved.is_dir() else resolved.parent
        relative_directory = directory.relative_to(self._paths.root)
        ancestors = [self._paths.root]
        current = self._paths.root
        for part in relative_directory.parts:
            current = current / part
            ancestors.append(current)

        documents: list[InstructionDocument] = []
        for ancestor in ancestors:
            path = ancestor / "AGENTS.md"
            content = _read_instruction(path, max_bytes=self._max_bytes)
            if content is None:
                continue
            source = path.relative_to(self._paths.root).as_posix()
            scope_path = ancestor.relative_to(self._paths.root).as_posix()
            documents.append(
                InstructionDocument(
                    source=source,
                    scope="." if scope_path == "." else scope_path,
                    content=content,
                )
            )
        return InstructionBundle(documents=tuple(documents))


def load_project_instructions(workspace: Path, *, max_bytes: int = 64_000) -> str:
    """Load a root AGENTS.md without following links outside the workspace."""

    path = workspace.resolve() / "AGENTS.md"
    return _read_instruction(path, max_bytes=max_bytes) or ""


def _read_instruction(path: Path, *, max_bytes: int) -> str | None:
    if not path.exists() and not path.is_symlink():
        return None
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
