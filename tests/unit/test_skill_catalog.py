from __future__ import annotations

from pathlib import Path

import pytest

import bluewhale_agent.skills.catalog as catalog_module
from bluewhale_agent.skills.catalog import SkillCatalog, SkillCatalogError
from bluewhale_agent.skills.models import SkillScope


def write_skill(
    root: Path,
    directory: str,
    *,
    name: str,
    description: str,
    body: str = "Follow the workflow.",
    hidden: bool = False,
) -> Path:
    skill = root / directory
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        f"name: {name}\n"
        f'description: "{description}"\n'
        f"disable-model-invocation: {'true' if hidden else 'false'}\n"
        "unknown-field: ignored\n"
        "---\n\n"
        f"# {name}\n\n{body}\n",
        encoding="utf-8",
    )
    return skill


def test_discovers_metadata_without_rendering_full_instructions(tmp_path: Path) -> None:
    skill = write_skill(
        tmp_path / ".bluewhale" / "skills",
        "python-testing",
        name="python-testing",
        description="Use for pytest and <unit tests>.",
        body="PRIVATE WORKFLOW BODY",
    )
    scripts = skill / "scripts"
    scripts.mkdir()
    (scripts / "run.sh").write_text("#!/bin/sh\n", encoding="utf-8")
    references = skill / "references"
    references.mkdir()
    (references / "guide.md").write_text("Guide\n", encoding="utf-8")

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    descriptor = catalog.get("python-testing")
    assert descriptor is not None
    assert descriptor.scope is SkillScope.PROJECT
    rendered = catalog.render_for_model()
    assert "python-testing" in rendered
    assert "&lt;unit tests&gt;" in rendered
    assert "PRIVATE WORKFLOW BODY" not in rendered

    loaded = catalog.load("python-testing")
    assert "PRIVATE WORKFLOW BODY" in loaded.instructions
    assert loaded.resources == ("references/guide.md", "scripts/run.sh")


def test_project_skill_overrides_user_skill_with_same_name(tmp_path: Path) -> None:
    home = tmp_path / "home"
    write_skill(
        home / ".bluewhale" / "skills",
        "review",
        name="code-review",
        description="User review workflow.",
    )
    write_skill(
        tmp_path / ".agents" / "skills",
        "review",
        name="code-review",
        description="Project review workflow.",
    )

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=home)

    selected = catalog.get("code-review")
    assert selected is not None
    assert selected.scope is SkillScope.PROJECT
    assert selected.description == "Project review workflow."
    assert any("code-review" in warning and "override" in warning for warning in catalog.warnings)


def test_hidden_skill_is_available_only_for_explicit_loading(tmp_path: Path) -> None:
    write_skill(
        tmp_path / ".bluewhale" / "skills",
        "release",
        name="release",
        description="Publish a release.",
        hidden=True,
    )
    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert catalog.get("release") is None
    assert catalog.get("release", allow_hidden=True) is not None
    assert "release" not in catalog.render_for_model()
    with pytest.raises(SkillCatalogError, match="not available for model invocation"):
        catalog.load("release")
    assert catalog.load("release", allow_hidden=True).descriptor.name == "release"


@pytest.mark.parametrize("name", ["BadName", "-leading", "trailing-", "two--dash", "a" * 65])
def test_invalid_skill_names_are_skipped(tmp_path: Path, name: str) -> None:
    write_skill(
        tmp_path / ".bluewhale" / "skills",
        "invalid",
        name=name,
        description="Invalid name.",
    )

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert catalog.skills == ()
    assert catalog.warnings


def test_missing_description_and_symlinked_skill_are_skipped(tmp_path: Path) -> None:
    root = tmp_path / ".bluewhale" / "skills"
    missing = root / "missing"
    missing.mkdir(parents=True)
    (missing / "SKILL.md").write_text("---\nname: missing\n---\nBody\n", encoding="utf-8")
    outside = tmp_path / "outside.md"
    outside.write_text(
        "---\nname: linked\ndescription: linked\n---\nBody\n",
        encoding="utf-8",
    )
    linked = root / "linked"
    linked.mkdir()
    (linked / "SKILL.md").symlink_to(outside)

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert catalog.skills == ()
    assert len(catalog.warnings) == 2


def test_resource_inventory_does_not_follow_symlinks(tmp_path: Path) -> None:
    skill = write_skill(
        tmp_path / ".bluewhale" / "skills",
        "safe",
        name="safe",
        description="Safe resources.",
    )
    scripts = skill / "scripts"
    scripts.mkdir()
    outside = tmp_path / "outside.sh"
    outside.write_text("danger\n", encoding="utf-8")
    (scripts / "linked.sh").symlink_to(outside)

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert catalog.load("safe").resources == ()


def test_skill_cannot_escape_boundary_when_parent_is_replaced_by_symlink(
    tmp_path: Path,
) -> None:
    root = tmp_path / ".bluewhale" / "skills"
    original = write_skill(root, "safe", name="safe", description="Safe skill.")
    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")
    backup = root / "safe-backup"
    original.rename(backup)
    outside = tmp_path.parent / f"{tmp_path.name}-outside-skill"
    write_skill(outside, "package", name="safe", description="Escaped skill.")
    original.symlink_to(outside / "package", target_is_directory=True)

    with pytest.raises(SkillCatalogError, match="outside its trusted boundary"):
        catalog.load("safe")


def test_nofollow_open_blocks_parent_swap_after_validation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    root = tmp_path / ".bluewhale" / "skills"
    original = write_skill(root, "safe", name="safe", description="Safe skill.")
    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")
    outside = tmp_path.parent / f"{tmp_path.name}-race-skill"
    escaped = write_skill(
        outside,
        "package",
        name="safe",
        description="Escaped skill.",
        body="SECRET OUTSIDE BODY",
    )
    real_validate = catalog_module._validate_skill_file
    swapped = False

    def validate_then_swap(path: Path, *, boundary: Path) -> None:
        nonlocal swapped
        real_validate(path, boundary=boundary)
        if not swapped:
            swapped = True
            original.rename(root / "safe-backup")
            original.symlink_to(escaped, target_is_directory=True)

    monkeypatch.setattr(catalog_module, "_validate_skill_file", validate_then_swap)

    with pytest.raises(SkillCatalogError, match="could not be opened safely"):
        catalog.load("safe")


def test_deeply_nested_skill_is_not_discovered(tmp_path: Path) -> None:
    root = tmp_path / ".agents" / "skills"
    nested = "/".join(f"level-{index}" for index in range(7))
    write_skill(root, nested, name="too-deep", description="Too deep.")

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert catalog.get("too-deep", allow_hidden=True) is None


def test_project_skills_keep_their_own_discovery_budget(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_module, "_MAX_SKILLS_PER_SCOPE", 2)
    home = tmp_path / "home"
    for index in range(3):
        write_skill(
            home / ".bluewhale" / "skills",
            f"user-{index}",
            name=f"user-{index}",
            description="User skill.",
        )
    write_skill(
        tmp_path / ".bluewhale" / "skills",
        "project-important",
        name="project-important",
        description="Project skill.",
    )

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=home)

    assert catalog.get("project-important") is not None
    assert len([skill for skill in catalog.skills if skill.scope is SkillScope.USER]) == 2
    assert any("user Skill discovery limit" in warning for warning in catalog.warnings)


def test_discovery_stops_scanning_an_excessively_wide_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_module, "_MAX_VISITED_DIRECTORIES", 3)
    root = tmp_path / ".bluewhale" / "skills"
    for index in range(8):
        (root / f"empty-{index}").mkdir(parents=True)

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert any("directory traversal limit" in warning for warning in catalog.warnings)


def test_discovery_stops_enumerating_an_excessively_wide_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_module, "_MAX_VISITED_ENTRIES", 3)
    root = tmp_path / ".bluewhale" / "skills"
    for index in range(8):
        (root / f"entry-{index}.txt").parent.mkdir(parents=True, exist_ok=True)
        (root / f"entry-{index}.txt").write_text("ignored", encoding="utf-8")

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert any("entry traversal limit" in warning for warning in catalog.warnings)


def test_resource_inventory_rejects_an_excessively_wide_tree(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_module, "_MAX_VISITED_DIRECTORIES", 3)
    skill = write_skill(
        tmp_path / ".bluewhale" / "skills",
        "wide",
        name="wide",
        description="Wide resources.",
    )
    for index in range(8):
        (skill / "references" / f"empty-{index}").mkdir(parents=True)
    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    with pytest.raises(SkillCatalogError, match="resource directory traversal limit"):
        catalog.load("wide")


def test_resource_inventory_rejects_an_excessively_wide_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(catalog_module, "_MAX_VISITED_ENTRIES", 3)
    skill = write_skill(
        tmp_path / ".bluewhale" / "skills",
        "wide-files",
        name="wide-files",
        description="Wide resources.",
    )
    references = skill / "references"
    references.mkdir()
    for index in range(8):
        (references / f"file-{index}.txt").write_text("data", encoding="utf-8")
    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    with pytest.raises(SkillCatalogError, match="resource entry traversal limit"):
        catalog.load("wide-files")


def test_platform_without_nofollow_support_fails_closed(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    write_skill(
        tmp_path / ".bluewhale" / "skills",
        "safe",
        name="safe",
        description="Safe skill.",
    )
    monkeypatch.setattr(catalog_module.os, "O_NOFOLLOW", 0)

    catalog = SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")

    assert catalog.skills == ()
    assert any("secure Skill loading is not supported" in item for item in catalog.warnings)
