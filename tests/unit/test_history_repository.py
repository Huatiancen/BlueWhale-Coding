from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from bluewhale_agent.domain.models import RunStatus, StopReason
from bluewhale_agent.history.repository import (
    HistoryConflictError,
    HistoryRecord,
    HistoryRepository,
)


def record(
    root: Path,
    run_id: str,
    *,
    status: RunStatus = RunStatus.RUNNING,
    created_at: datetime | None = None,
) -> HistoryRecord:
    timestamp = created_at or datetime(2026, 8, 29, 1, 0, tzinfo=UTC)
    workspace = root / f"workspace-{run_id}"
    workspace.mkdir(exist_ok=True)
    return HistoryRecord(
        id=run_id,
        task=f"Task {run_id}",
        workspace=workspace,
        workspace_name=workspace.name,
        status=status,
        stop_reason=None,
        verified=None,
        final_answer=None,
        steps_taken=0,
        repair_attempts=0,
        created_at=timestamp,
        updated_at=timestamp,
        events_path=root / "runs" / run_id / "events.jsonl",
    )


def test_repository_creates_local_database_and_round_trips_records(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    original = record(tmp_path, "run-one")

    repository.add(original)

    assert repository.database_path == tmp_path / "history.sqlite3"
    assert repository.runs_root == tmp_path / "runs"
    assert repository.get("run-one") == original
    assert repository.contains("run-one") is True
    assert repository.contains("missing") is False


def test_repository_lists_newest_updates_first_and_updates_existing_record(
    tmp_path: Path,
) -> None:
    repository = HistoryRepository(tmp_path)
    first = record(tmp_path, "first")
    second = record(
        tmp_path,
        "second",
        created_at=first.created_at + timedelta(minutes=1),
    )
    repository.add(first)
    repository.add(second)
    completed = replace(
        first,
        status=RunStatus.COMPLETED,
        stop_reason=StopReason.COMPLETED,
        final_answer="Done",
        updated_at=second.updated_at + timedelta(minutes=1),
    )

    repository.update(completed)

    assert repository.list() == (completed, second)


def test_repository_rejects_duplicate_ids(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    original = record(tmp_path, "duplicate")
    repository.add(original)

    with pytest.raises(HistoryConflictError, match="duplicate"):
        repository.add(original)


def test_workspace_availability_is_evaluated_from_current_local_state(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    original = record(tmp_path, "available")
    repository.add(original)

    assert repository.get("available").workspace_available is True  # type: ignore[union-attr]
    original.workspace.rmdir()
    assert repository.get("available").workspace_available is False  # type: ignore[union-attr]


def test_recover_interrupted_marks_all_active_statuses_as_stopped(tmp_path: Path) -> None:
    repository = HistoryRepository(tmp_path)
    active_statuses = (
        RunStatus.INITIALIZING,
        RunStatus.RUNNING,
        RunStatus.WAITING_APPROVAL,
        RunStatus.VERIFYING,
    )
    for status in active_statuses:
        repository.add(record(tmp_path, status.value, status=status))
    repository.add(record(tmp_path, "completed", status=RunStatus.COMPLETED))
    recovered_at = datetime(2026, 8, 29, 2, 0, tzinfo=UTC)

    recovered = repository.recover_interrupted(recovered_at)

    assert recovered == len(active_statuses)
    for status in active_statuses:
        restored = repository.get(status.value)
        assert restored is not None
        assert restored.status is RunStatus.STOPPED
        assert restored.stop_reason is StopReason.APP_INTERRUPTED
        assert restored.updated_at == recovered_at
    assert repository.get("completed").status is RunStatus.COMPLETED  # type: ignore[union-attr]
