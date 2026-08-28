from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

import pytest

from bluewhale_agent.agent.loop import AgentLoop, AgentRunResult
from bluewhale_agent.domain.events import EventKind
from bluewhale_agent.domain.models import Action, MessageRole, ModelResponse, StopReason
from bluewhale_agent.evidence.ledger import EvidenceKind
from tests.fakes import FakeModelProvider

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "sample_project"


def action(action_id: str, tool_name: str, **arguments: object) -> Action:
    return Action(id=action_id, tool_name=tool_name, arguments=arguments)


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


@pytest.mark.asyncio
async def test_create_file_workflow_records_diff_evidence_and_gui_events(
    tmp_path: Path,
) -> None:
    provider = FakeModelProvider(
        [
            response(
                actions=(
                    action(
                        "create-module",
                        "write_file",
                        path="greeting.py",
                        content='def greet(name: str) -> str:\n    return f"Hello, {name}!"\n',
                    ),
                    action("show-create-diff", "get_diff"),
                )
            ),
            response(content="Created greeting.py and recorded the local diff."),
        ]
    )

    result = await AgentLoop(
        run_id="workflow-create",
        workspace=tmp_path,
        provider=provider,
    ).run("Create a typed greeting helper")

    assert result.stop_reason is StopReason.PARTIALLY_VERIFIED
    assert (
        (tmp_path / "greeting.py")
        .read_text(encoding="utf-8")
        .endswith('return f"Hello, {name}!"\n')
    )
    diff = observation_for(result, "show-create-diff").content
    assert "--- /dev/null" in diff
    assert "+++ b/greeting.py" in diff
    assert any(
        item.kind is EvidenceKind.FILE_DIFF and item.verified
        for item in result.evidence_report.evidence
    )
    assert_gui_event_sequence(result)


@pytest.mark.asyncio
async def test_boundary_fix_passes_on_first_verification_round(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_python_path(monkeypatch)
    workspace = copy_sample_project(tmp_path)
    provider = FakeModelProvider(
        [
            response(
                actions=(
                    action(
                        "fix-zero",
                        "apply_patch",
                        path="calculator.py",
                        search="    return dividend / divisor\n",
                        replace=(
                            "    if divisor == 0:\n"
                            "        return None\n"
                            "    return dividend / divisor\n"
                        ),
                    ),
                    action("show-fixed-diff", "get_diff"),
                )
            ),
            response(content="Handled the zero-divisor boundary and verified it."),
        ]
    )

    result = await AgentLoop(
        run_id="workflow-first-pass",
        workspace=workspace,
        provider=provider,
    ).run("Fix safe_divide so a zero divisor returns None")

    assert result.stop_reason is StopReason.COMPLETED
    assert result.verified is True
    assert result.verification is not None
    assert result.verification.rounds == 1
    assert result.repair_attempts == 0
    assert "if divisor == 0:" in (workspace / "calculator.py").read_text(encoding="utf-8")
    assert "+    if divisor == 0:" in observation_for(result, "show-fixed-diff").content
    evidence_kinds = {item.kind for item in result.evidence_report.evidence}
    assert {EvidenceKind.FILE_DIFF, EvidenceKind.TEST_RESULT} <= evidence_kinds
    assert_gui_event_sequence(result)


@pytest.mark.asyncio
async def test_failed_verification_is_repaired_and_second_round_passes(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    configure_python_path(monkeypatch)
    workspace = copy_sample_project(tmp_path)
    provider = FakeModelProvider(
        [
            response(
                actions=(
                    action(
                        "incomplete-fix",
                        "apply_patch",
                        path="calculator.py",
                        search="    return dividend / divisor\n",
                        replace=(
                            "    if divisor == 0:\n"
                            "        return 0\n"
                            "    return dividend / divisor\n"
                        ),
                    ),
                    action("show-incomplete-diff", "get_diff"),
                )
            ),
            response(content="The initial boundary guard is ready."),
            response(
                actions=(
                    action(
                        "repair-zero",
                        "apply_patch",
                        path="calculator.py",
                        search="        return 0\n",
                        replace="        return None\n",
                    ),
                    action("show-repaired-diff", "get_diff"),
                )
            ),
        ]
    )

    result = await AgentLoop(
        run_id="workflow-repair-pass",
        workspace=workspace,
        provider=provider,
    ).run("Fix safe_divide and recover if the first implementation is incomplete")

    assert result.stop_reason is StopReason.COMPLETED
    assert result.verified is True
    assert result.verification is not None
    assert result.verification.rounds == 2
    assert result.repair_attempts == 1
    assert [item.status.value for item in result.verification.results] == ["failed", "passed"]
    final_source = (workspace / "calculator.py").read_text(encoding="utf-8")
    assert "return None" in final_source
    assert "return 0" not in final_source
    final_diff = observation_for(result, "show-repaired-diff").content
    assert "+        return None" in final_diff
    assert "+        return 0" not in final_diff
    failed_test, passed_test = [
        item for item in result.evidence_report.evidence if item.kind is EvidenceKind.TEST_RESULT
    ]
    assert failed_test.verified is False
    assert passed_test.verified is True
    assert_gui_event_sequence(result)

    repair_messages = provider.calls[2][0]
    assert any(
        message.role is MessageRole.USER and "Verification failed" in (message.content or "")
        for message in repair_messages
    )


def copy_sample_project(tmp_path: Path) -> Path:
    workspace = tmp_path / "sample_project"
    shutil.copytree(
        FIXTURE_ROOT,
        workspace,
        ignore=shutil.ignore_patterns("__pycache__", ".pytest_cache", "*.pyc"),
    )
    return workspace


def configure_python_path(monkeypatch: pytest.MonkeyPatch) -> None:
    executable_directory = str(Path(sys.executable).parent)
    monkeypatch.setenv(
        "PATH",
        executable_directory + os.pathsep + os.environ.get("PATH", ""),
    )


def observation_for(result: AgentRunResult, action_id: str):
    return next(item for item in result.observations if item.action_id == action_id)


def assert_gui_event_sequence(result: AgentRunResult) -> None:
    kinds = [stored.event.kind for stored in result.trajectory.events_after(0)]
    assert kinds[0] is EventKind.RUN_STARTED
    assert kinds[-1] is EventKind.RUN_FINISHED
    assert kinds.count(EventKind.ACTION_REQUESTED) == kinds.count(EventKind.OBSERVATION_RECEIVED)
    assert kinds.index(EventKind.MODEL_RESPONSE) < kinds.index(EventKind.ACTION_REQUESTED)
    assert kinds.index(EventKind.VERIFICATION_FINISHED) < kinds.index(EventKind.RUN_FINISHED)
