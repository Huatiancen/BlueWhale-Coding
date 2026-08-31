from __future__ import annotations

from pathlib import Path

import pytest

from bluewhale_agent.domain.models import Action
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.runtime.permissions import PermissionDecision, PermissionPolicy
from bluewhale_agent.skills.catalog import SkillCatalog
from bluewhale_agent.tools.base import ToolContext, ToolExecutionError
from bluewhale_agent.tools.skills import LoadSkillTool


def create_skill(tmp_path: Path, *, hidden: bool = False) -> SkillCatalog:
    root = tmp_path / ".bluewhale" / "skills" / "python-testing"
    root.mkdir(parents=True)
    (root / "SKILL.md").write_text(
        "---\n"
        "name: python-testing\n"
        "description: Run Python tests safely.\n"
        f"disable-model-invocation: {'true' if hidden else 'false'}\n"
        "---\n\n"
        "# Workflow\n\nFollow pytest conventions.\n",
        encoding="utf-8",
    )
    scripts = root / "scripts"
    scripts.mkdir()
    (scripts / "test.sh").write_text("pytest -q\n", encoding="utf-8")
    return SkillCatalog.discover(workspace=tmp_path, user_home=tmp_path / "home")


@pytest.mark.asyncio
async def test_load_skill_returns_instructions_and_safe_metadata(tmp_path: Path) -> None:
    tool = LoadSkillTool(create_skill(tmp_path))
    context = ToolContext(paths=WorkspacePaths(tmp_path))

    first = await tool.invoke({"name": "python-testing"}, context)
    second = await tool.invoke({"name": "python-testing"}, context)

    assert first == second
    assert "Follow pytest conventions" in first.content
    assert "scripts/test.sh" in first.content
    assert first.metadata == {
        "skill_name": "python-testing",
        "source": ".bluewhale/skills/python-testing/SKILL.md",
        "scope": "project",
        "summary": "Run Python tests safely.",
        "resource_count": 1,
    }


@pytest.mark.asyncio
async def test_load_skill_rejects_unknown_and_model_hidden_skills(tmp_path: Path) -> None:
    context = ToolContext(paths=WorkspacePaths(tmp_path))
    visible_tool = LoadSkillTool(create_skill(tmp_path))
    with pytest.raises(ToolExecutionError, match="Unknown skill"):
        await visible_tool.invoke({"name": "missing"}, context)

    hidden_root = tmp_path / "hidden-workspace"
    hidden_root.mkdir()
    hidden_tool = LoadSkillTool(create_skill(hidden_root, hidden=True))
    hidden_context = ToolContext(paths=WorkspacePaths(hidden_root))
    with pytest.raises(ToolExecutionError, match="not available for model invocation"):
        await hidden_tool.invoke({"name": "python-testing"}, hidden_context)


def test_load_skill_permission_is_read_only_and_never_asks() -> None:
    result = PermissionPolicy().evaluate(
        Action(id="load-1", tool_name="load_skill", arguments={"name": "python-testing"})
    )

    assert result.decision is PermissionDecision.ALLOW
