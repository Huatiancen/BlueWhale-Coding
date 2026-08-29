from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bluewhale_agent.domain.events import EventKind, RunEvent
from bluewhale_agent.domain.models import RunStatus, StopReason
from bluewhale_agent.history.projector import HistoryProjectionError, project_history
from bluewhale_agent.trajectory.store import StoredEvent


def stored(sequence: int, kind: EventKind, payload: dict[str, object]) -> StoredEvent:
    occurred = datetime(2026, 8, 29, 1, 0, tzinfo=UTC) + timedelta(seconds=sequence)
    return StoredEvent(
        sequence=sequence,
        recorded_at=occurred,
        event=RunEvent(
            run_id="run-one",
            kind=kind,
            payload=payload,
            occurred_at=occurred,
        ),
    )


def test_projector_rebuilds_completed_run_summary(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    events_path = tmp_path / "history" / "runs" / "run-one" / "events.jsonl"
    events = [
        stored(1, EventKind.RUN_STARTED, {"task": "Fix tests"}),
        stored(
            2,
            EventKind.STATE_CHANGED,
            {"status": "running", "steps_taken": 2, "repair_attempts": 1},
        ),
        stored(3, EventKind.VERIFICATION_FINISHED, {"outcome": {"passed": True}}),
        stored(
            4,
            EventKind.RUN_FINISHED,
            {
                "status": "completed",
                "stop_reason": "completed",
                "verified": True,
                "final_answer": "Fixed.",
            },
        ),
    ]

    result = project_history("run-one", workspace, events_path, events)

    assert result.id == "run-one"
    assert result.task == "Fix tests"
    assert result.workspace == workspace.resolve()
    assert result.workspace_name == "project"
    assert result.status is RunStatus.COMPLETED
    assert result.stop_reason is StopReason.COMPLETED
    assert result.verified is True
    assert result.final_answer == "Fixed."
    assert result.steps_taken == 2
    assert result.repair_attempts == 1
    assert result.created_at == events[0].recorded_at
    assert result.updated_at == events[-1].recorded_at
    assert result.events_path == events_path


def test_projector_tolerates_missing_optional_fields(tmp_path: Path) -> None:
    workspace = tmp_path / "missing-workspace"
    events = [
        stored(1, EventKind.RUN_STARTED, {"task": "Inspect"}),
        stored(2, EventKind.STATE_CHANGED, {"status": "running"}),
    ]

    result = project_history(
        "run-one",
        workspace,
        tmp_path / "runs" / "run-one" / "events.jsonl",
        events,
    )

    assert result.status is RunStatus.RUNNING
    assert result.stop_reason is None
    assert result.verified is None
    assert result.final_answer is None
    assert result.steps_taken == 0


def test_projector_requires_a_valid_run_started_event(tmp_path: Path) -> None:
    with pytest.raises(HistoryProjectionError, match="run_started"):
        project_history(
            "run-one",
            tmp_path,
            tmp_path / "events.jsonl",
            [stored(1, EventKind.STATE_CHANGED, {"status": "running"})],
        )
