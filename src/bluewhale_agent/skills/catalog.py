"""Bounded discovery and safe loading for local Agent Skills packages."""

from __future__ import annotations

import os
import re
import stat
from html import escape
from pathlib import Path

from bluewhale_agent.skills.models import LoadedSkill, SkillDescriptor, SkillScope

_NAME_PATTERN = re.compile(r"^(?!-)(?!.*--)[a-z0-9-]{1,64}(?<!-)$")
_MAX_SKILL_BYTES = 64_000
_MAX_DESCRIPTION_CHARS = 1_024
_MAX_DISCOVERY_DEPTH = 6
_MAX_SKILLS_PER_SCOPE = 128
_MAX_RESOURCES = 256
_MAX_VISITED_DIRECTORIES = 1_024
_MAX_VISITED_ENTRIES = 4_096
_MAX_CATALOG_CHARS = 16_000
_RESOURCE_DIRECTORIES = ("assets", "references", "scripts")


class SkillCatalogError(ValueError):
    """A requested Skill is unavailable or no longer safe to load."""


class SkillCatalog:
    """Immutable snapshot of discoverable Skill metadata."""

    def __init__(
        self,
        skills: tuple[SkillDescriptor, ...],
        warnings: tuple[str, ...] = (),
    ) -> None:
        self.skills = skills
        self.warnings = warnings
        self._by_name = {skill.name: skill for skill in skills}

    @classmethod
    def discover(
        cls,
        *,
        workspace: Path,
        user_home: Path | None = None,
    ) -> SkillCatalog:
        workspace = workspace.resolve()
        home = (user_home or Path.home()).resolve()
        roots = (
            (home / ".bluewhale" / "skills", SkillScope.USER, home),
            (home / ".agents" / "skills", SkillScope.USER, home),
            (workspace / ".bluewhale" / "skills", SkillScope.PROJECT, workspace),
            (workspace / ".agents" / "skills", SkillScope.PROJECT, workspace),
        )
        selected: dict[str, SkillDescriptor] = {}
        warnings: list[str] = []
        discovered = {SkillScope.USER: 0, SkillScope.PROJECT: 0}
        limited_scopes: set[SkillScope] = set()
        for root, scope, display_root in roots:
            paths, traversal_limit = _skill_files(root, boundary=display_root)
            if traversal_limit is not None:
                warnings.append(f"{root}: Skill {traversal_limit} traversal limit reached")
            for path in paths:
                if discovered[scope] >= _MAX_SKILLS_PER_SCOPE:
                    if scope not in limited_scopes:
                        warnings.append(
                            f"{scope.value} Skill discovery limit reached at "
                            f"{_MAX_SKILLS_PER_SCOPE} entries"
                        )
                        limited_scopes.add(scope)
                    continue
                discovered[scope] += 1
                try:
                    descriptor = _descriptor(path, scope=scope, display_root=display_root)
                except SkillCatalogError as error:
                    warnings.append(f"{path}: {error}")
                    continue
                current = selected.get(descriptor.name)
                if current is None:
                    selected[descriptor.name] = descriptor
                    continue
                if current.scope is SkillScope.USER and scope is SkillScope.PROJECT:
                    warnings.append(
                        f"Project skill {descriptor.name} override user skill {current.source}"
                    )
                    selected[descriptor.name] = descriptor
                else:
                    warnings.append(
                        f"Duplicate skill {descriptor.name} ignored from {descriptor.source}"
                    )
        return cls(tuple(selected.values()), tuple(warnings))

    def get(self, name: str, *, allow_hidden: bool = False) -> SkillDescriptor | None:
        descriptor = self._by_name.get(name)
        if descriptor is None:
            return None
        if descriptor.disable_model_invocation and not allow_hidden:
            return None
        return descriptor

    def render_for_model(self) -> str:
        visible = [skill for skill in self.skills if not skill.disable_model_invocation]
        if not visible:
            return ""
        lines = ["<available_skills>"]
        for skill in visible:
            block = (
                "  <skill>\n"
                f"    <name>{escape(skill.name)}</name>\n"
                f"    <description>{escape(skill.description)}</description>\n"
                f"    <scope>{skill.scope.value}</scope>\n"
                "  </skill>"
            )
            candidate = "\n".join((*lines, block, "</available_skills>"))
            if len(candidate) > _MAX_CATALOG_CHARS:
                lines.append("  <!-- additional Skills omitted by context budget -->")
                break
            lines.append(block)
        lines.append("</available_skills>")
        return "\n".join(lines)

    def load(self, name: str, *, allow_hidden: bool = False) -> LoadedSkill:
        descriptor = self._by_name.get(name)
        if descriptor is None:
            raise SkillCatalogError(f"Unknown skill: {name}")
        if descriptor.disable_model_invocation and not allow_hidden:
            raise SkillCatalogError(f"Skill {name} is not available for model invocation")
        instructions = _read_skill_text(descriptor.path, boundary=descriptor.boundary)
        return LoadedSkill(
            descriptor=descriptor,
            instructions=instructions,
            resources=_resource_inventory(
                descriptor.path.parent, boundary=descriptor.boundary
            ),
        )


def _skill_files(root: Path, *, boundary: Path) -> tuple[tuple[Path, ...], str | None]:
    if not root.is_dir() or root.is_symlink():
        return (), None
    if not root.resolve().is_relative_to(boundary.resolve()):
        return (), None
    files: list[Path] = []
    stack = [(root, 0)]
    visited_directories = 0
    visited_entries = 0
    while stack:
        current, depth = stack.pop()
        visited_directories += 1
        if visited_directories > _MAX_VISITED_DIRECTORIES:
            return tuple(sorted(files)), "directory"
        child_directories: list[Path] = []
        try:
            iterator = os.scandir(current)
        except OSError:
            continue
        with iterator:
            for entry in iterator:
                visited_entries += 1
                if visited_entries > _MAX_VISITED_ENTRIES:
                    return tuple(sorted(files)), "entry"
                try:
                    if entry.name == "SKILL.md":
                        files.append(current / entry.name)
                    elif depth < _MAX_DISCOVERY_DEPTH and entry.is_dir(
                        follow_symlinks=False
                    ):
                        child_directories.append(current / entry.name)
                except OSError:
                    continue
        stack.extend(
            (directory, depth + 1)
            for directory in sorted(child_directories, reverse=True)
        )
    return tuple(sorted(files)), None


def _descriptor(path: Path, *, scope: SkillScope, display_root: Path) -> SkillDescriptor:
    content = _read_skill_text(path, boundary=display_root)
    metadata = _frontmatter(content)
    name = metadata.get("name", "")
    description = metadata.get("description", "")
    if _NAME_PATTERN.fullmatch(name) is None:
        raise SkillCatalogError("Skill name is invalid")
    if not description:
        raise SkillCatalogError("Skill description is required")
    if len(description) > _MAX_DESCRIPTION_CHARS:
        raise SkillCatalogError("Skill description is too long")
    hidden = metadata.get("disable-model-invocation", "false").lower()
    if hidden not in {"true", "false"}:
        raise SkillCatalogError("disable-model-invocation must be true or false")
    relative = path.relative_to(display_root).as_posix()
    source = relative if scope is SkillScope.PROJECT else f"~/{relative}"
    return SkillDescriptor(
        name=name,
        description=description,
        source=source,
        scope=scope,
        path=path,
        boundary=display_root,
        disable_model_invocation=hidden == "true",
    )


def _validate_skill_file(path: Path, *, boundary: Path) -> None:
    if path.is_symlink():
        raise SkillCatalogError("SKILL.md must not be a symbolic link")
    if not path.is_file():
        raise SkillCatalogError("SKILL.md must be a regular file")
    if not path.resolve().is_relative_to(boundary.resolve()):
        raise SkillCatalogError("SKILL.md is outside its trusted boundary")
    if path.stat().st_size > _MAX_SKILL_BYTES:
        raise SkillCatalogError("SKILL.md is too large")


def _read_skill_text(path: Path, *, boundary: Path) -> str:
    """Read SKILL.md through no-follow directory descriptors.

    The preliminary validation produces useful diagnostics. The descriptor-relative
    open is the security boundary: replacing any parent with a symlink between
    discovery and loading cannot redirect the read outside ``boundary``.
    """

    _require_secure_open_support()
    _validate_skill_file(path, boundary=boundary)
    relative = _relative_to_boundary(path, boundary)
    directory_flags = os.O_RDONLY | getattr(os, "O_DIRECTORY", 0)
    nofollow = getattr(os, "O_NOFOLLOW", 0)
    current_fd = -1
    file_fd = -1
    try:
        current_fd = os.open(boundary, directory_flags | nofollow)
        for part in relative.parts[:-1]:
            next_fd = os.open(part, directory_flags | nofollow, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        file_fd = os.open(relative.name, os.O_RDONLY | nofollow, dir_fd=current_fd)
        details = os.fstat(file_fd)
        if not stat.S_ISREG(details.st_mode):
            raise SkillCatalogError("SKILL.md must be a regular file")
        if details.st_size > _MAX_SKILL_BYTES:
            raise SkillCatalogError("SKILL.md is too large")
        chunks: list[bytes] = []
        remaining = _MAX_SKILL_BYTES + 1
        while remaining:
            chunk = os.read(file_fd, min(remaining, 16_384))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        payload = b"".join(chunks)
        if len(payload) > _MAX_SKILL_BYTES:
            raise SkillCatalogError("SKILL.md is too large")
        try:
            return payload.decode("utf-8")
        except UnicodeDecodeError as error:
            raise SkillCatalogError("SKILL.md must be UTF-8 text") from error
    except SkillCatalogError:
        raise
    except (NotImplementedError, OSError) as error:
        raise SkillCatalogError("SKILL.md could not be opened safely") from error
    finally:
        if file_fd >= 0:
            os.close(file_fd)
        if current_fd >= 0:
            os.close(current_fd)


def _relative_to_boundary(path: Path, boundary: Path) -> Path:
    try:
        relative = path.relative_to(boundary)
    except ValueError as error:
        raise SkillCatalogError("SKILL.md is outside its trusted boundary") from error
    if not relative.parts or any(part in {"", ".", ".."} for part in relative.parts):
        raise SkillCatalogError("SKILL.md is outside its trusted boundary")
    return relative


def _require_secure_open_support() -> None:
    supports_dir_fd: set[object] = getattr(os, "supports_dir_fd", set())
    supports_fd: set[object] = getattr(os, "supports_fd", set())
    supports_follow: set[object] = getattr(os, "supports_follow_symlinks", set())
    supported = (
        bool(getattr(os, "O_NOFOLLOW", 0))
        and bool(getattr(os, "O_DIRECTORY", 0))
        and os.open in supports_dir_fd
        and os.stat in supports_dir_fd
        and os.stat in supports_follow
        and os.scandir in supports_fd
    )
    if not supported:
        raise SkillCatalogError(
            "secure Skill loading is not supported on this platform"
        )


def _frontmatter(content: str) -> dict[str, str]:
    lines = content.splitlines()
    if not lines or lines[0].strip() != "---":
        raise SkillCatalogError("SKILL.md must start with YAML frontmatter")
    metadata: dict[str, str] = {}
    for line in lines[1:]:
        if line.strip() == "---":
            return metadata
        if not line or line[0].isspace() or ":" not in line:
            continue
        key, value = line.split(":", 1)
        normalized = value.strip()
        if len(normalized) >= 2 and normalized[0] == normalized[-1] and normalized[0] in "\"'":
            normalized = normalized[1:-1]
        metadata[key.strip()] = normalized
    raise SkillCatalogError("SKILL.md frontmatter is not closed")


def _resource_inventory(skill_root: Path, *, boundary: Path) -> tuple[str, ...]:
    _require_secure_open_support()
    resources: list[str] = []
    skill_fd = _open_directory(skill_root, boundary=boundary)
    visited = [0]
    visited_entries = [0]
    try:
        for directory_name in _RESOURCE_DIRECTORIES:
            try:
                resource_fd = os.open(
                    directory_name,
                    os.O_RDONLY
                    | getattr(os, "O_DIRECTORY", 0)
                    | getattr(os, "O_NOFOLLOW", 0),
                    dir_fd=skill_fd,
                )
            except FileNotFoundError:
                continue
            except OSError:
                continue
            try:
                _walk_resource_directory(
                    resource_fd,
                    prefix=Path(directory_name),
                    depth=0,
                    visited=visited,
                    visited_entries=visited_entries,
                    resources=resources,
                )
            finally:
                os.close(resource_fd)
            if len(resources) >= _MAX_RESOURCES:
                break
    finally:
        os.close(skill_fd)
    return tuple(sorted(resources[:_MAX_RESOURCES]))


def _open_directory(path: Path, *, boundary: Path) -> int:
    _require_secure_open_support()
    relative = _relative_to_boundary(path, boundary)
    flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    current_fd = -1
    try:
        current_fd = os.open(boundary, flags)
        for part in relative.parts:
            next_fd = os.open(part, flags, dir_fd=current_fd)
            os.close(current_fd)
            current_fd = next_fd
        return current_fd
    except (NotImplementedError, OSError) as error:
        if current_fd >= 0:
            os.close(current_fd)
        raise SkillCatalogError("Skill directory could not be opened safely") from error


def _walk_resource_directory(
    directory_fd: int,
    *,
    prefix: Path,
    depth: int,
    visited: list[int],
    visited_entries: list[int],
    resources: list[str],
) -> None:
    visited[0] += 1
    if visited[0] > _MAX_VISITED_DIRECTORIES:
        raise SkillCatalogError("Skill resource directory traversal limit reached")
    names: list[str] = []
    try:
        iterator = os.scandir(directory_fd)
        with iterator:
            for entry in iterator:
                visited_entries[0] += 1
                if visited_entries[0] > _MAX_VISITED_ENTRIES:
                    raise SkillCatalogError(
                        "Skill resource entry traversal limit reached"
                    )
                names.append(entry.name)
    except SkillCatalogError:
        raise
    except (NotImplementedError, OSError) as error:
        raise SkillCatalogError("Skill resources could not be listed safely") from error
    flags = (
        os.O_RDONLY | getattr(os, "O_DIRECTORY", 0) | getattr(os, "O_NOFOLLOW", 0)
    )
    for name in names:
        if len(resources) >= _MAX_RESOURCES:
            return
        try:
            details = os.stat(name, dir_fd=directory_fd, follow_symlinks=False)
        except OSError:
            continue
        relative = prefix / name
        if stat.S_ISREG(details.st_mode):
            resources.append(relative.as_posix())
            continue
        if not stat.S_ISDIR(details.st_mode) or depth >= _MAX_DISCOVERY_DEPTH:
            continue
        try:
            child_fd = os.open(name, flags, dir_fd=directory_fd)
        except OSError:
            continue
        try:
            _walk_resource_directory(
                child_fd,
                prefix=relative,
                depth=depth + 1,
                visited=visited,
                visited_entries=visited_entries,
                resources=resources,
            )
        finally:
            os.close(child_fd)
