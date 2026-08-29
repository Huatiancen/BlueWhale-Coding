from __future__ import annotations

from pathlib import Path

from bluewhale_agent.domain.events import EventKind, RunEvent
from bluewhale_agent.domain.models import RunStatus, StopReason
from bluewhale_agent.history.importer import LegacyHistoryImporter
from bluewhale_agent.history.repository import HistoryRepository
from bluewhale_agent.trajectory.store import TrajectoryStore


def create_legacy_run(workspace: Path, run_id: str) -> None:
    store = TrajectoryStore(workspace, run_id)
    store.append(RunEvent(run_id=run_id, kind=EventKind.RUN_STARTED, payload={"task": "Old"}))
    store.append(
        RunEvent(
            run_id=run_id,
            kind=EventKind.RUN_FINISHED,
            payload={
                "status": "completed",
                "stop_reason": "completed",
                "verified": None,
                "final_answer": "Imported.",
            },
        )
    )


def test_importer_copies_legacy_runs_once_without_deleting_source(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    create_legacy_run(workspace, "legacy-one")
    source = workspace / ".bluewhale" / "runs" / "legacy-one" / "events.jsonl"
    repository = HistoryRepository(tmp_path / "history")
    importer = LegacyHistoryImporter(repository)

    first = importer.import_workspace(workspace)
    second = importer.import_workspace(workspace)

    assert first.imported == 1
    assert first.failed == 0
    assert second.imported == 0
    assert second.skipped == 1
    assert source.exists()
    record = repository.get("legacy-one")
    assert record is not None
    assert record.final_answer == "Imported."
    assert record.events_path.read_text(encoding="utf-8") == source.read_text(encoding="utf-8")


def test_importer_isolates_a_corrupt_run(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    create_legacy_run(workspace, "valid")
    corrupt = workspace / ".bluewhale" / "runs" / "corrupt"
    corrupt.mkdir(parents=True)
    (corrupt / "events.jsonl").write_text("broken\nrecord\n", encoding="utf-8")
    repository = HistoryRepository(tmp_path / "history")

    result = LegacyHistoryImporter(repository).import_workspace(workspace)

    assert result.imported == 1
    assert result.failed == 1
    assert repository.contains("valid") is True
    assert repository.contains("corrupt") is False


def test_importer_marks_unfinished_legacy_run_as_interrupted(tmp_path: Path) -> None:
    workspace = tmp_path / "project"
    workspace.mkdir()
    store = TrajectoryStore(workspace, "unfinished")
    store.append(
        RunEvent(run_id="unfinished", kind=EventKind.RUN_STARTED, payload={"task": "Old"})
    )
    store.append(
        RunEvent(
            run_id="unfinished",
            kind=EventKind.STATE_CHANGED,
            payload={"status": "waiting_approval"},
        )
    )
    repository = HistoryRepository(tmp_path / "history")

    LegacyHistoryImporter(repository).import_workspace(workspace)

    record = repository.get("unfinished")
    assert record is not None
    assert record.status is RunStatus.STOPPED
    assert record.stop_reason is StopReason.APP_INTERRUPTED
