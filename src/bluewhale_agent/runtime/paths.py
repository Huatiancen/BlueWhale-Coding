"""Workspace-scoped path resolution for local tools."""

from __future__ import annotations

import os
from pathlib import Path


class PathAccessError(ValueError):
    """Raised when a requested path violates the workspace boundary."""


class PathAccessDeniedError(PathAccessError):
    """Raised when a path is present but forbidden by the safety boundary."""


class WorkspacePaths:
    """Resolve and enumerate paths without escaping the selected workspace."""

    IGNORED_DIRECTORIES = frozenset(
        {
            ".bluewhale",
            ".git",
            ".mypy_cache",
            ".pytest_cache",
            ".ruff_cache",
            ".venv",
            "__pycache__",
            "build",
            "dist",
            "node_modules",
            "venv",
        }
    )

    def __init__(self, root: Path) -> None:
        self.root = root.resolve(strict=True)
        if not self.root.is_dir():
            raise PathAccessError("Workspace root must be a directory")

    def resolve(self, requested: str, *, must_exist: bool = True) -> Path:
        """Return a canonical workspace path or reject unsafe input."""

        relative = Path(requested)
        if relative.is_absolute():
            raise PathAccessDeniedError("absolute paths are not allowed")
        if self._is_protected(relative):
            raise PathAccessDeniedError("The requested path is protected")

        candidate = (self.root / relative).resolve(strict=False)
        try:
            candidate.relative_to(self.root)
        except ValueError as exc:
            raise PathAccessDeniedError("The requested path is outside the workspace") from exc

        if must_exist and not candidate.exists():
            raise PathAccessError(f"Path does not exist: {requested}")
        return candidate

    def iter_files(self, requested: str = ".") -> list[Path]:
        """Return sorted regular files below a safe workspace path."""

        start = self.resolve(requested)
        if start.is_file():
            return [start]
        if not start.is_dir():
            raise PathAccessError(f"Path is not a file or directory: {requested}")

        files: list[Path] = []
        for directory, directory_names, file_names in os.walk(start, followlinks=False):
            directory_names[:] = sorted(
                name
                for name in directory_names
                if name not in self.IGNORED_DIRECTORIES
                and not (Path(directory) / name).is_symlink()
            )
            for name in sorted(file_names):
                path = Path(directory) / name
                relative = path.relative_to(self.root)
                if self._is_protected(relative) or path.is_symlink():
                    continue
                try:
                    resolved = self.resolve(relative.as_posix())
                except PathAccessError:
                    continue
                if resolved.is_file():
                    files.append(resolved)
        return sorted(files, key=lambda path: path.relative_to(self.root).as_posix())

    @staticmethod
    def _is_protected(path: Path) -> bool:
        return any(
            part in {".bluewhale", ".git"} or part == ".env" or part.startswith(".env.")
            for part in path.parts
        )
