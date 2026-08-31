from pathlib import Path

import pytest

from bluewhale_agent.context.instructions import (
    InstructionResolver,
    ProjectInstructionsError,
    load_project_instructions,
)


def test_loads_root_agents_md(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Always run pytest.\n", encoding="utf-8")

    assert load_project_instructions(tmp_path) == "Always run pytest."


def test_rejects_agents_md_symlink(tmp_path: Path) -> None:
    outside = tmp_path.parent / "outside-agents.md"
    outside.write_text("unsafe", encoding="utf-8")
    (tmp_path / "AGENTS.md").symlink_to(outside)

    with pytest.raises(ProjectInstructionsError, match="symbolic link"):
        load_project_instructions(tmp_path)


def test_caps_project_instructions(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("x" * 20, encoding="utf-8")

    with pytest.raises(ProjectInstructionsError, match="too large"):
        load_project_instructions(tmp_path, max_bytes=10)


def test_resolver_merges_root_to_nearest_directory(tmp_path: Path) -> None:
    (tmp_path / "AGENTS.md").write_text("Root rule.\n", encoding="utf-8")
    source = tmp_path / "src"
    feature = source / "feature"
    feature.mkdir(parents=True)
    (source / "AGENTS.md").write_text("Source rule.\n", encoding="utf-8")
    (feature / "AGENTS.md").write_text("Feature rule.\n", encoding="utf-8")
    target = feature / "new_file.py"

    bundle = InstructionResolver(tmp_path).resolve_for(target.relative_to(tmp_path))

    assert [document.source for document in bundle.documents] == [
        "AGENTS.md",
        "src/AGENTS.md",
        "src/feature/AGENTS.md",
    ]
    assert [document.scope for document in bundle.documents] == [".", "src", "src/feature"]
    assert bundle.render().index("Root rule") < bundle.render().index("Feature rule")


def test_resolver_keeps_sibling_rules_isolated(tmp_path: Path) -> None:
    left = tmp_path / "left"
    right = tmp_path / "right"
    left.mkdir()
    right.mkdir()
    (left / "AGENTS.md").write_text("Left only.\n", encoding="utf-8")
    (right / "AGENTS.md").write_text("Right only.\n", encoding="utf-8")

    bundle = InstructionResolver(tmp_path).resolve_for("left/app.py")

    assert "Left only" in bundle.render()
    assert "Right only" not in bundle.render()


def test_resolver_rejects_target_outside_workspace(tmp_path: Path) -> None:
    with pytest.raises(ProjectInstructionsError, match="outside workspace"):
        InstructionResolver(tmp_path).resolve_for("../outside.py")
