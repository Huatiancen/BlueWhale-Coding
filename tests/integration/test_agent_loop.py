from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from bluewhale_agent.agent.checkpoints import CheckpointPhase, RunCheckpoint, RunCheckpointStore
from bluewhale_agent.agent.loop import AgentLoop
from bluewhale_agent.domain.events import EventKind
from bluewhale_agent.domain.models import (
    Action,
    Limits,
    Message,
    MessageRole,
    ModelResponse,
    ObservationStatus,
    RunStatus,
    StopReason,
)
from bluewhale_agent.evidence.ledger import EvidenceKind
from bluewhale_agent.providers.base import ModelProtocolError, StreamInterruptedError
from bluewhale_agent.runtime.permissions import PermissionMode, PermissionResult
from bluewhale_agent.skills.models import MAX_ACTIVE_SKILLS
from tests.fakes import FakeModelProvider


def response(
    *,
    content: str | None = None,
    actions: tuple[Action, ...] = (),
) -> ModelResponse:
    return ModelResponse(
        content=content,
        tool_calls=actions,
        finish_reason="tool_calls" if actions else "stop",
    )


def action(action_id: str, tool_name: str, **arguments: object) -> Action:
    return Action(id=action_id, tool_name=tool_name, arguments=arguments)


class InterruptedStreamProvider:
    async def stream(self, messages, tools, on_delta):
        del messages, tools, on_delta
        raise StreamInterruptedError(
            ModelResponse(content="已完成部分检查。", finish_reason="interrupted")
        )


@pytest.mark.asyncio
async def test_stream_interruption_preserves_partial_answer_and_failed_checkpoint(
    tmp_path: Path,
) -> None:
    result = await AgentLoop(
        run_id="interrupted-stream",
        workspace=tmp_path,
        provider=InterruptedStreamProvider(),
        limits=Limits(max_api_retries=0),
    ).run("检查项目")

    assert result.stop_reason is StopReason.API_ERROR
    assert result.final_answer == "已完成部分检查。"
    checkpoint = RunCheckpointStore(tmp_path, "interrupted-stream").load_latest()
    assert checkpoint is not None
    assert checkpoint.phase is CheckpointPhase.FAILED


class RecoveringStreamProvider:
    def __init__(self) -> None:
        self.calls = 0

    async def stream(self, messages, tools, on_delta):
        del messages, tools, on_delta
        self.calls += 1
        if self.calls == 1:
            raise StreamInterruptedError(
                ModelResponse(content="正在检查。", finish_reason="interrupted")
            )
        return response(content="检查完成。")


@pytest.mark.asyncio
async def test_stream_interruption_repairs_history_and_retries(tmp_path: Path) -> None:
    provider = RecoveringStreamProvider()

    result = await AgentLoop(
        run_id="recover-stream",
        workspace=tmp_path,
        provider=provider,
        limits=Limits(max_api_retries=1),
    ).run("检查项目")

    assert provider.calls == 2
    assert result.stop_reason is StopReason.COMPLETED
    assert result.final_answer == "检查完成。"


@pytest.mark.asyncio
async def test_resume_checkpoint_reconciles_pending_side_effect_without_replay(
    tmp_path: Path,
) -> None:
    pending = action("write-pending", "write_file", path="app.py", content="changed\n")
    store = RunCheckpointStore(tmp_path, "resume-pending")
    checkpoint = store.save(
        RunCheckpoint(
            run_id="resume-pending",
            task="修改 app.py",
            phase=CheckpointPhase.TOOL_EXECUTING,
            messages=(
                Message(
                    role=MessageRole.ASSISTANT,
                    content=None,
                    tool_calls=(pending,),
                ),
            ),
            pending_action=pending,
        )
    )
    provider = FakeModelProvider([response(content="已检查中断状态，无需重放。")])

    result = await AgentLoop(
        run_id="resume-pending",
        workspace=tmp_path,
        provider=provider,
        resume_checkpoint=checkpoint,
    ).run("继续")

    sent = provider.calls[0][0]
    assert any("修改 app.py" in (message.content or "") for message in sent)
    assert any(
        message.role is MessageRole.TOOL
        and message.tool_call_id == "write-pending"
        and "interrupted" in (message.content or "")
        for message in sent
    )
    assert not (tmp_path / "app.py").exists()
    assert result.stop_reason is StopReason.COMPLETED


@pytest.mark.asyncio
async def test_successful_run_finishes_with_completed_checkpoint(tmp_path: Path) -> None:
    result = await AgentLoop(
        run_id="checkpoint-complete",
        workspace=tmp_path,
        provider=FakeModelProvider([response(content="完成。")]),
    ).run("解释项目")

    assert result.stop_reason is StopReason.COMPLETED
    checkpoint = RunCheckpointStore(tmp_path, "checkpoint-complete").load_latest()
    assert checkpoint is not None
    assert checkpoint.phase is CheckpointPhase.COMPLETED
    assert checkpoint.messages[-1].content == "完成。"


@pytest.mark.asyncio
async def test_initial_history_is_copied_into_the_first_model_request(
    tmp_path: Path,
) -> None:
    initial_history = (
        Message(role=MessageRole.USER, content="先解释这个模块"),
        Message(role=MessageRole.ASSISTANT, content="这个模块负责计算。"),
    )
    provider = FakeModelProvider([response(content="继续说明完成。")])

    await AgentLoop(
        run_id="continued-run",
        workspace=tmp_path,
        provider=provider,
        initial_history=initial_history,
    ).run("继续说明边界条件")

    sent = provider.calls[0][0]
    contents = [message.content or "" for message in sent]
    assert any("继续说明边界条件" in content for content in contents)
    assert "先解释这个模块" in contents
    assert "这个模块负责计算。" in contents
    previous_user = contents.index("先解释这个模块")
    previous_assistant = contents.index("这个模块负责计算。")
    current_user = next(
        index for index, content in enumerate(contents) if "继续说明边界条件" in content
    )
    assert previous_user < previous_assistant < current_user
    assert initial_history == (
        Message(role=MessageRole.USER, content="先解释这个模块"),
        Message(role=MessageRole.ASSISTANT, content="这个模块负责计算。"),
    )


@pytest.mark.asyncio
async def test_read_then_answer_preserves_protocol_history_and_trajectory(
    tmp_path: Path,
) -> None:
    (tmp_path / "app.py").write_text("answer = 42\n", encoding="utf-8")
    provider = FakeModelProvider(
        [
            response(actions=(action("read-1", "read_file", path="app.py"),)),
            response(content="The configured answer is 42."),
        ]
    )

    result = await AgentLoop(
        run_id="read-answer",
        workspace=tmp_path,
        provider=provider,
    ).run("Read app.py and report the answer")

    assert result.status is RunStatus.COMPLETED
    assert result.stop_reason is StopReason.COMPLETED
    assert result.final_answer == "The configured answer is 42."
    assert [item.status for item in result.observations] == [ObservationStatus.SUCCESS]
    assert result.actions[0].tool_name == "read_file"
    assert any(item.kind is EvidenceKind.FILE_READ for item in result.evidence_report.evidence)
    second_messages = provider.calls[1][0]
    assert any(message.role is MessageRole.TOOL for message in second_messages)

    events = result.trajectory.events_after(0)
    assert events[0].event.kind is EventKind.RUN_STARTED
    assert events[-1].event.kind is EventKind.RUN_FINISHED
    assert [event.sequence for event in events] == list(range(1, len(events) + 1))


@pytest.mark.asyncio
async def test_out_of_scope_change_prevents_verified_completion(tmp_path: Path) -> None:
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_dummy.py").write_text(
        "import unittest\n\n"
        "class Dummy(unittest.TestCase):\n"
        "    def test_ok(self): self.assertTrue(True)\n",
        encoding="utf-8",
    )
    provider = FakeModelProvider(
        [
            response(
                actions=(
                    action("allowed", "write_file", path="allowed.py", content="ok = True\n"),
                    action("outside", "write_file", path="outside.py", content="extra = True\n"),
                )
            ),
            response(content="Implemented and verified."),
        ]
    )

    result = await AgentLoop(
        run_id="scope-gate",
        workspace=tmp_path,
        provider=provider,
        allowed_change_paths=("allowed.py",),
    ).run("Only modify allowed.py")

    assert result.status is RunStatus.FAILED
    assert result.stop_reason is StopReason.VERIFICATION_FAILED
    assert result.verification is not None
    assert result.verification.passed is False
    assert result.verification.level.value == "failed"


@pytest.mark.asyncio
async def test_scoped_agents_rules_are_loaded_after_target_file_is_selected(
    tmp_path: Path,
) -> None:
    source = tmp_path / "src"
    source.mkdir()
    (tmp_path / "AGENTS.md").write_text("Root convention.\n", encoding="utf-8")
    (source / "AGENTS.md").write_text("Use pathlib in this directory.\n", encoding="utf-8")
    (source / "app.py").write_text("value = 1\n", encoding="utf-8")
    provider = FakeModelProvider(
        [
            response(actions=(action("read-scoped", "read_file", path="src/app.py"),)),
            response(actions=(action("read-scoped-again", "read_file", path="src/app.py"),)),
            response(content="文件已检查。"),
        ]
    )

    result = await AgentLoop(
        run_id="scoped-instructions",
        workspace=tmp_path,
        provider=provider,
    ).run("检查 src/app.py")

    second_context = "\n".join(message.content or "" for message in provider.calls[1][0])
    assert "Root convention" in second_context
    assert "Use pathlib in this directory" in second_context
    applied = [
        item.event.payload
        for item in result.trajectory.events_after(0)
        if item.event.kind is EventKind.INSTRUCTIONS_APPLIED
    ]
    assert applied[0]["action_id"] == "read-scoped"
    assert [item["source"] for item in applied[0]["documents"]] == [
        "AGENTS.md",
        "src/AGENTS.md",
    ]
    assert [item.status for item in result.observations] == [
        ObservationStatus.ERROR,
        ObservationStatus.SUCCESS,
    ]
    assert result.final_answer == "文件已检查。"


@pytest.mark.asyncio
async def test_skill_catalog_is_disclosed_before_full_skill_is_loaded(tmp_path: Path) -> None:
    skill = tmp_path / ".bluewhale" / "skills" / "python-testing"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: python-testing\n"
        "description: Use when running Python tests.\n"
        "---\n\n"
        "PRIVATE SKILL WORKFLOW\n",
        encoding="utf-8",
    )
    provider = FakeModelProvider(
        [
            response(actions=(action("skill-1", "load_skill", name="python-testing"),)),
            response(content="已按 Skill 检查。"),
        ]
    )

    result = await AgentLoop(
        run_id="skill-disclosure",
        workspace=tmp_path,
        provider=provider,
        skill_user_home=tmp_path / "home",
    ).run("运行 Python 测试")

    first_context = "\n".join(message.content or "" for message in provider.calls[0][0])
    assert "python-testing" in first_context
    assert "PRIVATE SKILL WORKFLOW" not in first_context
    assert any(
        schema["function"]["name"] == "load_skill" for schema in provider.calls[0][1]
    )
    second_system = "\n".join(
        message.content or ""
        for message in provider.calls[1][0]
        if message.role is MessageRole.SYSTEM
    )
    assert "PRIVATE SKILL WORKFLOW" in second_system
    second_context = "\n".join(message.content or "" for message in provider.calls[1][0])
    assert second_context.count("PRIVATE SKILL WORKFLOW") == 1
    load_results = [
        message
        for message in provider.calls[1][0]
        if message.role is MessageRole.TOOL and message.tool_call_id == "skill-1"
    ]
    assert len(load_results) == 1
    assert "PRIVATE SKILL WORKFLOW" not in (load_results[0].content or "")
    applied = [
        item.event.payload
        for item in result.trajectory.events_after(0)
        if item.event.kind is EventKind.SKILL_APPLIED
    ]
    assert applied == [
        {
            "name": "python-testing",
            "source": ".bluewhale/skills/python-testing/SKILL.md",
            "scope": "project",
            "trigger": "model",
            "summary": "Use when running Python tests.",
            "resource_count": 0,
        }
    ]
    checkpoint = (tmp_path / ".bluewhale" / "runs" / "skill-disclosure" / "checkpoint.json")
    assert "PRIVATE SKILL WORKFLOW" not in checkpoint.read_text(encoding="utf-8")
    observations = [
        item.event.payload["observation"]
        for item in result.trajectory.events_after(0)
        if item.event.kind is EventKind.OBSERVATION_RECEIVED
        and item.event.payload["observation"]["action_id"] == "skill-1"
    ]
    assert observations[0]["content"] == ""
    stored_checkpoint = RunCheckpointStore(tmp_path, "skill-disclosure").load_latest()
    assert stored_checkpoint is not None
    assert stored_checkpoint.active_skill_names == ("python-testing",)


@pytest.mark.asyncio
async def test_loading_same_skill_twice_emits_one_application_event(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code.\n---\nReview carefully.\n",
        encoding="utf-8",
    )
    provider = FakeModelProvider(
        [
            response(actions=(action("skill-1", "load_skill", name="review"),)),
            response(actions=(action("skill-2", "load_skill", name="review"),)),
            response(content="完成。"),
        ]
    )

    result = await AgentLoop(
        run_id="skill-repeat",
        workspace=tmp_path,
        provider=provider,
        skill_user_home=tmp_path / "home",
    ).run("审查代码")

    assert len(
        [
            item
            for item in result.trajectory.events_after(0)
            if item.event.kind is EventKind.SKILL_APPLIED
        ]
    ) == 1


@pytest.mark.asyncio
async def test_loading_more_than_active_skill_limit_returns_visible_error(
    tmp_path: Path,
) -> None:
    actions = []
    for index in range(MAX_ACTIVE_SKILLS + 1):
        name = f"skill-{index}"
        skill = tmp_path / ".agents" / "skills" / name
        skill.mkdir(parents=True)
        (skill / "SKILL.md").write_text(
            f"---\nname: {name}\ndescription: Skill {index}.\n---\nBODY-{index}\n",
            encoding="utf-8",
        )
        actions.append(action(f"load-{index}", "load_skill", name=name))
    provider = FakeModelProvider(
        [response(actions=tuple(actions)), response(content="已处理容量错误。")]
    )

    result = await AgentLoop(
        run_id="skill-capacity",
        workspace=tmp_path,
        provider=provider,
        skill_user_home=tmp_path / "home",
    ).run("加载全部技能")

    applied = [
        item
        for item in result.trajectory.events_after(0)
        if item.event.kind is EventKind.SKILL_APPLIED
    ]
    assert len(applied) == MAX_ACTIVE_SKILLS
    final_observation = [
        item.event.payload["observation"]
        for item in result.trajectory.events_after(0)
        if item.event.kind is EventKind.OBSERVATION_RECEIVED
        and item.event.payload["observation"]["action_id"]
        == f"load-{MAX_ACTIVE_SKILLS}"
    ][0]
    assert final_observation["status"] == "error"
    assert "active Skill limit" in final_observation["summary"]


@pytest.mark.asyncio
async def test_explicit_skill_preloads_hidden_skill_and_passes_arguments_separately(
    tmp_path: Path,
) -> None:
    skill = tmp_path / ".bluewhale" / "skills" / "release"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\n"
        "name: release\n"
        "description: Publish a release.\n"
        "disable-model-invocation: true\n"
        "---\n\n"
        "HIDDEN RELEASE WORKFLOW\n",
        encoding="utf-8",
    )
    provider = FakeModelProvider([response(content="已准备发布。")])

    result = await AgentLoop(
        run_id="explicit-skill",
        workspace=tmp_path,
        provider=provider,
        skill_user_home=tmp_path / "home",
    ).run("/skill:release prepare version 1.2.0")

    first = provider.calls[0][0]
    systems = "\n".join(
        message.content or "" for message in first if message.role is MessageRole.SYSTEM
    )
    users = "\n".join(
        message.content or "" for message in first if message.role is MessageRole.USER
    )
    assert "HIDDEN RELEASE WORKFLOW" in systems
    assert "prepare version 1.2.0" in users
    assert "/skill:release" not in users
    applied = [
        item.event.payload
        for item in result.trajectory.events_after(0)
        if item.event.kind is EventKind.SKILL_APPLIED
    ]
    assert applied[0]["trigger"] == "explicit"


@pytest.mark.asyncio
async def test_unknown_explicit_skill_fails_without_calling_model(tmp_path: Path) -> None:
    provider = FakeModelProvider([])

    result = await AgentLoop(
        run_id="missing-explicit-skill",
        workspace=tmp_path,
        provider=provider,
        skill_user_home=tmp_path / "home",
    ).run("/skill:missing do work")

    assert provider.calls == []
    assert result.status is RunStatus.FAILED
    assert result.stop_reason is StopReason.TOOL_ERROR
    assert result.final_answer == "无法加载 Skill：Unknown skill: missing"


@pytest.mark.asyncio
async def test_resume_checkpoint_reloads_active_skill_from_current_disk(tmp_path: Path) -> None:
    skill = tmp_path / ".agents" / "skills" / "review"
    skill.mkdir(parents=True)
    (skill / "SKILL.md").write_text(
        "---\nname: review\ndescription: Review code.\n---\nCURRENT REVIEW WORKFLOW\n",
        encoding="utf-8",
    )
    checkpoint = RunCheckpoint(
        run_id="resume-active-skill",
        task="审查项目",
        phase=CheckpointPhase.INTERRUPTED,
        active_skill_names=("review",),
    )
    provider = FakeModelProvider([response(content="恢复完成。")])

    await AgentLoop(
        run_id="resume-active-skill",
        workspace=tmp_path,
        provider=provider,
        resume_checkpoint=checkpoint,
        skill_user_home=tmp_path / "home",
    ).run("继续")

    system_context = "\n".join(
        message.content or ""
        for message in provider.calls[0][0]
        if message.role is MessageRole.SYSTEM
    )
    assert "CURRENT REVIEW WORKFLOW" in system_context


@pytest.mark.asyncio
async def test_search_modify_and_verify_uses_local_tools(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_python_path(monkeypatch)
    write_python_project(tmp_path)
    provider = FakeModelProvider(
        [
            response(actions=(action("search-1", "search_text", query="return 1"),)),
            response(
                actions=(
                    action(
                        "patch-1",
                        "apply_patch",
                        path="calculator.py",
                        search="return 1",
                        replace="return 2",
                    ),
                )
            ),
            response(content="The implementation has been corrected."),
        ]
    )

    result = await AgentLoop(
        run_id="modify-verify",
        workspace=tmp_path,
        provider=provider,
    ).run("Fix calculator.value")

    assert result.status is RunStatus.COMPLETED
    assert result.verified is True
    assert result.verification is not None
    assert result.verification.passed is True
    assert (tmp_path / "calculator.py").read_text(
        encoding="utf-8"
    ) == "def value():\n    return 2\n"
    assert [item.tool_name for item in result.actions[:2]] == ["search_text", "apply_patch"]
    assert any(item.kind is EvidenceKind.TEST_RESULT for item in result.evidence_report.evidence)
    events = result.trajectory.events_after(0)
    changes = next(
        stored for stored in events if stored.event.kind is EventKind.CHANGESET_RECORDED
    )
    assert changes.event.payload["additions"] == 1
    assert changes.event.payload["deletions"] == 1
    assert changes.event.payload["files"][0]["path"] == "calculator.py"
    assert events.index(changes) < len(events) - 1


@pytest.mark.asyncio
async def test_failed_verification_gets_one_model_repair_then_passes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configure_python_path(monkeypatch)
    write_python_project(tmp_path)
    provider = FakeModelProvider(
        [
            response(
                actions=(
                    action(
                        "bad-patch",
                        "apply_patch",
                        path="calculator.py",
                        search="return 1",
                        replace="return 3",
                    ),
                )
            ),
            response(content="The change is ready."),
            response(
                actions=(
                    action(
                        "repair-patch",
                        "apply_patch",
                        path="calculator.py",
                        search="return 3",
                        replace="return 2",
                    ),
                )
            ),
        ]
    )

    result = await AgentLoop(
        run_id="repair-pass",
        workspace=tmp_path,
        provider=provider,
    ).run("Fix calculator.value")

    assert result.stop_reason is StopReason.COMPLETED
    assert result.verification is not None
    assert result.verification.rounds == 2
    assert result.repair_attempts == 1
    assert [item.tool_name for item in result.actions].count("run_command") == 2
    assert (tmp_path / "calculator.py").read_text(encoding="utf-8").endswith("return 2\n")


@pytest.mark.asyncio
async def test_invalid_model_protocol_is_added_to_context_and_retried(tmp_path: Path) -> None:
    provider = FakeModelProvider(
        [
            ModelProtocolError("tool arguments are invalid JSON"),
            response(content="Recovered after correcting the tool call."),
        ]
    )

    result = await AgentLoop(
        run_id="protocol-retry",
        workspace=tmp_path,
        provider=provider,
    ).run("Inspect the project")

    assert result.stop_reason is StopReason.COMPLETED
    assert len(provider.calls) == 2
    assert any("invalid JSON" in (message.content or "") for message in provider.calls[1][0])


@pytest.mark.asyncio
async def test_unknown_tool_is_observed_and_model_can_retry(tmp_path: Path) -> None:
    provider = FakeModelProvider(
        [
            response(actions=(action("bad-tool", "delete_everything"),)),
            response(content="I stopped using the unsupported tool."),
        ]
    )

    result = await AgentLoop(
        run_id="tool-retry",
        workspace=tmp_path,
        provider=provider,
    ).run("Inspect safely")

    assert result.stop_reason is StopReason.COMPLETED
    assert result.observations[0].status is ObservationStatus.ERROR
    assert "Unknown tool" in result.observations[0].summary
    assert any("Unknown tool" in (message.content or "") for message in provider.calls[1][0])


@pytest.mark.asyncio
async def test_consecutive_protocol_errors_reach_the_configured_limit(tmp_path: Path) -> None:
    provider = FakeModelProvider(
        [ModelProtocolError("bad call 1"), ModelProtocolError("bad call 2")]
    )

    result = await AgentLoop(
        run_id="protocol-limit",
        workspace=tmp_path,
        provider=provider,
        limits=Limits(max_consecutive_format_errors=2),
    ).run("Inspect the project")

    assert result.status is RunStatus.FAILED
    assert result.stop_reason is StopReason.MODEL_PROTOCOL_ERROR
    assert result.steps_taken == 2
    assert result.trajectory.events_after(0)[-1].event.kind is EventKind.RUN_FINISHED


@pytest.mark.asyncio
async def test_unexpected_component_error_still_persists_terminal_event(tmp_path: Path) -> None:
    provider = FakeModelProvider([RuntimeError("unexpected provider failure")])

    result = await AgentLoop(
        run_id="unexpected-error",
        workspace=tmp_path,
        provider=provider,
    ).run("Inspect the project")

    assert result.status is RunStatus.FAILED
    assert result.stop_reason is StopReason.TOOL_ERROR
    terminal = result.trajectory.events_after(0)[-1].event
    assert terminal.kind is EventKind.RUN_FINISHED
    assert terminal.payload["stop_reason"] == StopReason.TOOL_ERROR.value


@pytest.mark.asyncio
async def test_step_limit_stops_an_endless_tool_loop(tmp_path: Path) -> None:
    (tmp_path / "app.py").write_text("value = 1\n", encoding="utf-8")
    provider = FakeModelProvider(
        [response(actions=(action("read-1", "read_file", path="app.py"),))]
    )

    result = await AgentLoop(
        run_id="step-limit",
        workspace=tmp_path,
        provider=provider,
        limits=Limits(max_steps=1),
    ).run("Keep reading")

    assert result.status is RunStatus.STOPPED
    assert result.stop_reason is StopReason.STEP_LIMIT
    assert result.steps_taken == 1
    assert len(result.observations) == 1


@pytest.mark.asyncio
async def test_wall_time_limit_is_checked_before_model_call(tmp_path: Path) -> None:
    ticks = iter((0.0, 901.0))
    provider = FakeModelProvider([])

    result = await AgentLoop(
        run_id="time-limit",
        workspace=tmp_path,
        provider=provider,
        limits=Limits(max_wall_time_seconds=900),
        clock=lambda: next(ticks),
    ).run("Do not exceed the deadline")

    assert result.status is RunStatus.STOPPED
    assert result.stop_reason is StopReason.TIME_LIMIT
    assert provider.calls == []


@pytest.mark.asyncio
async def test_pre_cancelled_run_finishes_without_calling_model(tmp_path: Path) -> None:
    cancelled = asyncio.Event()
    cancelled.set()
    provider = FakeModelProvider([])

    result = await AgentLoop(
        run_id="cancelled",
        workspace=tmp_path,
        provider=provider,
        cancel_event=cancelled,
    ).run("Do not start")

    assert result.status is RunStatus.STOPPED
    assert result.stop_reason is StopReason.USER_STOPPED
    assert provider.calls == []
    assert result.trajectory.events_after(0)[-1].event.kind is EventKind.RUN_FINISHED


@pytest.mark.asyncio
async def test_compiler_chain_requests_one_approval_then_runs_each_step(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    tool_bin = tmp_path / "tool-bin"
    tool_bin.mkdir()
    compiler = tool_bin / "g++"
    compiler.write_text(
        "\n".join(
            [
                f"#!{sys.executable}",
                "from pathlib import Path",
                "target = Path('main')",
                f"target.write_text(\"#!{sys.executable}\\nprint('compiled program ran')\\n\")",
                "target.chmod(0o755)",
            ]
        ),
        encoding="utf-8",
    )
    compiler.chmod(0o755)
    (tmp_path / "main.cpp").write_text("int main() {}\n", encoding="utf-8")
    monkeypatch.setenv("PATH", str(tool_bin) + os.pathsep + os.environ.get("PATH", ""))
    requested: list[PermissionResult] = []

    async def approve(_action: Action, permission: PermissionResult) -> bool:
        requested.append(permission)
        return True

    provider = FakeModelProvider(
        [
            response(
                actions=(
                    action(
                        "compile-run",
                        "run_command",
                        command="g++ main.cpp -o main && ./main",
                    ),
                )
            ),
            response(content="Compiled and ran the program."),
        ]
    )

    result = await AgentLoop(
        run_id="compile-chain",
        workspace=tmp_path,
        provider=provider,
        permission_mode=PermissionMode.BALANCED,
        approval_handler=approve,
    ).run("Compile and run main.cpp")

    assert result.status is RunStatus.COMPLETED
    assert len(requested) == 1
    assert "./main" in requested[0].reason
    observation = result.observations[0]
    assert observation.status is ObservationStatus.SUCCESS
    assert "compiled program ran" in observation.content
    assert len(observation.metadata["steps"]) == 2


def configure_python_path(monkeypatch: pytest.MonkeyPatch) -> None:
    executable_directory = str(Path(sys.executable).parent)
    monkeypatch.setenv("PATH", executable_directory + os.pathsep + os.environ.get("PATH", ""))


def write_python_project(workspace: Path) -> None:
    (workspace / "pyproject.toml").write_text(
        "[project]\nname = 'fixture'\n\n[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
        encoding="utf-8",
    )
    (workspace / "calculator.py").write_text(
        "def value():\n    return 1\n",
        encoding="utf-8",
    )
    tests = workspace / "tests"
    tests.mkdir()
    (tests / "test_calculator.py").write_text(
        "from calculator import value\n\ndef test_value():\n    assert value() == 2\n",
        encoding="utf-8",
    )
