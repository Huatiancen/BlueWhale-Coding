from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

import pytest

from bluewhale_agent.agent.loop import AgentLoop
from bluewhale_agent.domain.events import EventKind
from bluewhale_agent.domain.models import (
    Action,
    Limits,
    MessageRole,
    ModelResponse,
    ObservationStatus,
    RunStatus,
    StopReason,
)
from bluewhale_agent.evidence.ledger import EvidenceKind
from bluewhale_agent.providers.base import ModelProtocolError
from bluewhale_agent.runtime.permissions import PermissionMode, PermissionResult
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
