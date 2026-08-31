from pathlib import Path

import pytest

from bluewhale_agent.context.manager import (
    ContextBudgetError,
    ContextManager,
    context_char_count,
)
from bluewhale_agent.context.workspace_map import WorkspaceMap, WorkspaceMapBuilder
from bluewhale_agent.domain.models import (
    Action,
    Message,
    MessageRole,
    Observation,
    ObservationStatus,
    RunStatus,
)
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.skills.models import MAX_ACTIVE_SKILLS


def build_sample_workspace(tmp_path: Path) -> WorkspaceMap:
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'demo'\n", encoding="utf-8")
    source = tmp_path / "src" / "app.py"
    source.parent.mkdir()
    source.write_text(
        "class Service(Base):\n"
        "    def method(self):\n"
        "        return 1\n\n"
        "def add(a: int, b: int = 1) -> int:\n"
        "    return a + b\n\n"
        "async def fetch(url: str):\n"
        "    return url\n",
        encoding="utf-8",
    )
    (tmp_path / "web").mkdir()
    (tmp_path / "web" / "app.js").write_text("export const value = 1;\n", encoding="utf-8")
    (tmp_path / "node_modules").mkdir()
    (tmp_path / "node_modules" / "noise.js").write_text("noise\n", encoding="utf-8")
    return WorkspaceMapBuilder(WorkspacePaths(tmp_path)).build()


def make_tool_exchange(index: int, observation: Observation) -> list[Message]:
    action = Action(id=observation.action_id, tool_name="run_command", arguments={"index": index})
    return [
        Message(role=MessageRole.ASSISTANT, content=None, tool_calls=(action,)),
        Message(
            role=MessageRole.TOOL,
            content=f"raw-{index}",
            tool_call_id=observation.action_id,
        ),
    ]


def make_history(observations: list[Observation]) -> list[Message]:
    return [
        message
        for index, observation in enumerate(observations)
        for message in make_tool_exchange(index, observation)
    ]


def test_workspace_map_prioritizes_manifests_and_extracts_python_signatures(
    tmp_path: Path,
) -> None:
    workspace_map = build_sample_workspace(tmp_path)

    assert workspace_map.entries[0].path == "pyproject.toml"
    python_entry = next(entry for entry in workspace_map.entries if entry.path == "src/app.py")
    javascript_entry = next(entry for entry in workspace_map.entries if entry.path == "web/app.js")

    assert python_entry.language == "python"
    assert "class Service(Base)" in python_entry.symbols
    assert "def add(a: int, b: int = 1) -> int" in python_entry.symbols
    assert "async def fetch(url: str)" in python_entry.symbols
    assert all("method" not in symbol for symbol in python_entry.symbols)
    assert javascript_entry.language == "javascript"
    assert javascript_entry.symbols == ()
    assert all("node_modules" not in entry.path for entry in workspace_map.entries)


def test_workspace_map_survives_invalid_python_and_renders_metadata(tmp_path: Path) -> None:
    (tmp_path / "broken.py").write_text("def broken(:\n", encoding="utf-8")

    workspace_map = WorkspaceMapBuilder(WorkspacePaths(tmp_path)).build()
    rendered = workspace_map.render()

    assert workspace_map.entries[0].path == "broken.py"
    assert workspace_map.entries[0].symbols == ()
    assert "broken.py" in rendered
    assert "python" in rendered
    assert "bytes" in rendered
    assert "modified=" in rendered


def test_context_keeps_recent_five_observation_bodies_and_summarizes_older(
    tmp_path: Path,
) -> None:
    workspace_map = build_sample_workspace(tmp_path)
    observations = [
        Observation(
            action_id=f"call-{index}",
            status=ObservationStatus.SUCCESS,
            summary=f"summary-{index}",
            content=f"body-{index}-" + "x" * 40,
            metadata={"artifact_path": f"artifacts/{index}.log"},
            duration_ms=index,
        )
        for index in range(7)
    ]
    history = make_history(observations)

    messages = ContextManager(max_chars=10_000).build(
        system_prompt="system rules",
        task="repair the demo",
        status=RunStatus.RUNNING,
        unresolved_errors=(),
        working_set={"src/app.py": "def add(): ..."},
        workspace_map=workspace_map,
        history=history,
        observations=observations,
    )
    tool_content = {
        message.tool_call_id: message.content
        for message in messages
        if message.role is MessageRole.TOOL
    }

    assert "body-0" not in (tool_content["call-0"] or "")
    assert "summary-0" in (tool_content["call-0"] or "")
    assert "artifacts/0.log" in (tool_content["call-0"] or "")
    for index in range(2, 7):
        assert f"body-{index}" in (tool_content[f"call-{index}"] or "")


def test_old_failure_body_and_required_sections_survive_compression(tmp_path: Path) -> None:
    workspace_map = build_sample_workspace(tmp_path)
    observations = [
        Observation(
            action_id=f"call-{index}",
            status=ObservationStatus.ERROR if index == 0 else ObservationStatus.SUCCESS,
            summary=f"summary-{index}",
            content="critical traceback" if index == 0 else f"body-{index}",
            duration_ms=1,
        )
        for index in range(7)
    ]
    history = make_history(observations)

    messages = ContextManager(max_chars=10_000).build(
        system_prompt="system rules",
        task="repair the demo",
        status=RunStatus.VERIFYING,
        unresolved_errors=("tests are still failing",),
        working_set={"src/app.py": "relevant source"},
        workspace_map=workspace_map,
        history=history,
        observations=observations,
    )
    combined = "\n".join(message.content or "" for message in messages)

    assert "critical traceback" in combined
    assert "tests are still failing" in combined
    assert combined.index("repair the demo") < combined.index("tests are still failing")
    assert combined.index("tests are still failing") < combined.index("src/app.py")
    assert combined.index("src/app.py") < combined.index("# Workspace map")


def test_context_separates_available_and_active_skills(tmp_path: Path) -> None:
    messages = ContextManager(max_chars=10_000).build(
        system_prompt="system rules",
        task="run tests",
        status=RunStatus.RUNNING,
        unresolved_errors=(),
        working_set={},
        workspace_map=build_sample_workspace(tmp_path),
        history=(),
        observations=(),
        available_skills="<available_skills><skill>python-testing</skill></available_skills>",
        active_skills={"python-testing": "PRIVATE WORKFLOW"},
    )

    system_messages = [
        message.content or "" for message in messages if message.role is MessageRole.SYSTEM
    ]
    assert any(
        "Available Skills" in content and "python-testing" in content
        for content in system_messages
    )
    assert any("Active Skill: python-testing" in content for content in system_messages)
    assert any("PRIVATE WORKFLOW" in content for content in system_messages)


def test_large_active_skill_is_bounded_without_losing_current_task(tmp_path: Path) -> None:
    task = "TASK-MUST-STAY"
    messages = ContextManager(max_chars=8_000).build(
        system_prompt="system rules",
        task=task,
        status=RunStatus.RUNNING,
        unresolved_errors=(),
        working_set={},
        workspace_map=build_sample_workspace(tmp_path),
        history=(),
        observations=(),
        active_skills={"large": "PRIVATE-BEGIN\n" + "x" * 64_000 + "\nPRIVATE-END"},
    )
    combined = "\n".join(message.content or "" for message in messages)

    assert context_char_count(messages) <= 8_000
    assert task in combined
    assert "Active Skill: large" in combined
    assert "[Skill instructions truncated by BlueWhale context budget]" in combined


def test_each_active_skill_remains_visible_when_shared_budget_is_exhausted(
    tmp_path: Path,
) -> None:
    messages = ContextManager(max_chars=8_000).build(
        system_prompt="system rules",
        task="TASK-MUST-STAY",
        status=RunStatus.RUNNING,
        unresolved_errors=(),
        working_set={},
        workspace_map=build_sample_workspace(tmp_path),
        history=(),
        observations=(),
        active_skills={
            "first": "FIRST-SKILL-BODY\n" + "x" * 20_000,
            "second": "SECOND-SKILL-BODY\n" + "y" * 20_000,
        },
    )
    combined = "\n".join(message.content or "" for message in messages)

    assert "TASK-MUST-STAY" in combined
    assert "Active Skill: first" in combined
    assert "Active Skill: second" in combined
    assert "FIRST-SKILL-BODY" in combined
    assert "SECOND-SKILL-BODY" in combined


def test_context_rejects_more_active_skills_than_can_be_represented(
    tmp_path: Path,
) -> None:
    active_skills = {
        f"skill-{index}": "instructions" for index in range(MAX_ACTIVE_SKILLS + 1)
    }

    with pytest.raises(ContextBudgetError, match="active Skill limit"):
        ContextManager(max_chars=50_000).build(
            system_prompt="system rules",
            task="run tests",
            status=RunStatus.RUNNING,
            unresolved_errors=(),
            working_set={},
            workspace_map=build_sample_workspace(tmp_path),
            history=(),
            observations=(),
            active_skills=active_skills,
        )


def test_every_supported_active_skill_keeps_its_heading(tmp_path: Path) -> None:
    active_skills = {
        f"skill-{index}": f"BODY-{index}\n" + "x" * 2_000
        for index in range(MAX_ACTIVE_SKILLS)
    }

    messages = ContextManager(max_chars=8_000).build(
        system_prompt="system rules",
        task="TASK-MUST-STAY",
        status=RunStatus.RUNNING,
        unresolved_errors=(),
        working_set={},
        workspace_map=build_sample_workspace(tmp_path),
        history=(),
        observations=(),
        active_skills=active_skills,
    )
    combined = "\n".join(message.content or "" for message in messages)

    assert "TASK-MUST-STAY" in combined
    for name in active_skills:
        assert f"# Active Skill: {name}" in combined


def test_context_respects_budget_without_breaking_tool_pairs(tmp_path: Path) -> None:
    workspace_map = build_sample_workspace(tmp_path)
    observations = [
        Observation(
            action_id=f"call-{index}",
            status=ObservationStatus.SUCCESS,
            summary=f"summary-{index}",
            content=f"body-{index}-" + "z" * 500,
            duration_ms=1,
        )
        for index in range(9)
    ]
    history = make_history(observations)
    manager = ContextManager(max_chars=2_200)

    messages = manager.build(
        system_prompt="system rules",
        task="repair the demo",
        status=RunStatus.RUNNING,
        unresolved_errors=(),
        working_set={"src/app.py": "w" * 500},
        workspace_map=workspace_map,
        history=history,
        observations=observations,
    )

    assert context_char_count(messages) <= 2_200
    call_ids = {
        action.id
        for message in messages
        if message.role is MessageRole.ASSISTANT
        for action in message.tool_calls
    }
    result_ids = {
        message.tool_call_id for message in messages if message.role is MessageRole.TOOL
    }
    assert call_ids == result_ids
    assert {f"call-{index}" for index in range(4, 9)} <= result_ids


def test_budget_truncates_tool_bodies_before_current_task(tmp_path: Path) -> None:
    workspace_map = build_sample_workspace(tmp_path)
    task = "a" * 500 + "TASK-MUST-STAY" + "b" * 500
    observations = [
        Observation(
            action_id=f"call-{index}",
            status=ObservationStatus.SUCCESS,
            summary="large output",
            content="z" * 500,
            duration_ms=1,
        )
        for index in range(5)
    ]

    messages = ContextManager(max_chars=1_500).build(
        system_prompt="system",
        task=task,
        status=RunStatus.RUNNING,
        unresolved_errors=(),
        working_set={},
        workspace_map=workspace_map,
        history=make_history(observations),
        observations=observations,
    )
    combined = "\n".join(message.content or "" for message in messages)

    assert context_char_count(messages) <= 1_500
    assert "TASK-MUST-STAY" in combined
