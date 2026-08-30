from pathlib import Path

import pytest

from bluewhale_agent.context.instructions import ProjectInstructionsError, load_project_instructions


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
