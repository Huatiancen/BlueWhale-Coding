"""Conservative discovery of repository-declared verification commands."""

from __future__ import annotations

import json
import tomllib
from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.runtime.paths import WorkspacePaths


class VerificationKind(StrEnum):
    """Stable categories used to explain why a command is being run."""

    TEST = "test"
    LINT = "lint"
    TYPECHECK = "typecheck"
    BUILD = "build"


class VerificationCommand(BaseModel):
    """One command justified by a declaration in the selected workspace."""

    model_config = ConfigDict(frozen=True)

    command: str = Field(min_length=1)
    kind: VerificationKind
    source: str = Field(min_length=1)


_NODE_SCRIPTS = (
    ("test", VerificationKind.TEST),
    ("lint", VerificationKind.LINT),
    ("typecheck", VerificationKind.TYPECHECK),
    ("check", VerificationKind.TYPECHECK),
    ("build", VerificationKind.BUILD),
)


def discover_verification_commands(paths: WorkspacePaths) -> tuple[VerificationCommand, ...]:
    """Return only standard commands supported by files already in the repository."""

    commands: list[VerificationCommand] = []
    root = paths.root

    python_source = _python_test_source(root)
    if python_source is not None:
        commands.append(
            VerificationCommand(
                command="python -m pytest -q",
                kind=VerificationKind.TEST,
                source=python_source,
            )
        )

    commands.extend(_node_commands(root))

    if (root / "Cargo.toml").is_file():
        commands.append(
            VerificationCommand(
                command="cargo test",
                kind=VerificationKind.TEST,
                source="Cargo.toml",
            )
        )
    if (root / "go.mod").is_file():
        commands.append(
            VerificationCommand(
                command="go test ./...",
                kind=VerificationKind.TEST,
                source="go.mod",
            )
        )

    return tuple(commands)


def _python_test_source(root: Path) -> str | None:
    if (root / "pytest.ini").is_file():
        return "pytest.ini"

    pyproject = root / "pyproject.toml"
    if pyproject.is_file():
        try:
            document = tomllib.loads(pyproject.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, tomllib.TOMLDecodeError):
            return None
        tool = document.get("tool")
        if isinstance(tool, dict) and isinstance(tool.get("pytest"), dict):
            return "pyproject.toml"
        if _declares_pytest(document):
            return "pyproject.toml"

    if (root / "tox.ini").is_file():
        return "tox.ini"
    if pyproject.is_file() and (root / "tests").is_dir():
        return "tests/"
    return None


def _declares_pytest(document: dict[str, object]) -> bool:
    project = document.get("project")
    if not isinstance(project, dict):
        return False
    dependencies: list[object] = list(project.get("dependencies", []))
    optional = project.get("optional-dependencies")
    if isinstance(optional, dict):
        for group in optional.values():
            if isinstance(group, list):
                dependencies.extend(group)
    return any(isinstance(item, str) and item.lower().startswith("pytest") for item in dependencies)


def _node_commands(root: Path) -> tuple[VerificationCommand, ...]:
    manifest = root / "package.json"
    if not manifest.is_file():
        return ()
    try:
        document = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return ()
    if not isinstance(document, dict):
        return ()
    scripts = document.get("scripts")
    if not isinstance(scripts, dict):
        return ()

    manager = _node_package_manager(root)
    return tuple(
        VerificationCommand(
            command=f"{manager} run {name}",
            kind=kind,
            source="package.json",
        )
        for name, kind in _NODE_SCRIPTS
        if isinstance(scripts.get(name), str) and scripts[name].strip()
    )


def _node_package_manager(root: Path) -> str:
    if (root / "pnpm-lock.yaml").is_file():
        return "pnpm"
    if (root / "yarn.lock").is_file():
        return "yarn"
    return "npm"
