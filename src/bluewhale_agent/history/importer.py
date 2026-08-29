"""One-way import of legacy workspace-owned trajectories."""

from __future__ import annotations

import os
import shutil
from dataclasses import dataclass, replace
from pathlib import Path

from bluewhale_agent.domain.models import RunStatus, StopReason
from bluewhale_agent.history.projector import HistoryProjectionError, project_history
from bluewhale_agent.history.repository import HistoryRepository
from bluewhale_agent.trajectory.store import TrajectoryCorruptionError, TrajectoryStore


@dataclass(frozen=True, slots=True)
class ImportResult:
    imported: int = 0
    skipped: int = 0
    failed: int = 0


class LegacyHistoryImporter:
    """Copy valid legacy runs into application-owned local history."""

    def __init__(self, repository: HistoryRepository) -> None:
        self._repository = repository

    def import_workspace(self, workspace: Path) -> ImportResult:
        legacy_root = workspace.resolve(strict=False) / ".bluewhale" / "runs"
        if not legacy_root.is_dir():
            return ImportResult()
        imported = skipped = failed = 0
        for run_dir in sorted(path for path in legacy_root.iterdir() if path.is_dir()):
            run_id = run_dir.name
            if self._repository.contains(run_id):
                skipped += 1
                continue
            temporary: Path | None = None
            try:
                source = TrajectoryStore(workspace, run_id)
                events = source.events_after(0)
                target_dir = self._repository.runs_root / run_id
                target_dir.mkdir(parents=True, exist_ok=True)
                target = target_dir / "events.jsonl"
                temporary = target_dir / "events.jsonl.importing"
                shutil.copyfile(source.events_path, temporary)
                os.replace(temporary, target)
                record = project_history(run_id, workspace, target, events)
                if record.status in {
                    RunStatus.INITIALIZING,
                    RunStatus.RUNNING,
                    RunStatus.WAITING_APPROVAL,
                    RunStatus.VERIFYING,
                }:
                    record = replace(
                        record,
                        status=RunStatus.STOPPED,
                        stop_reason=StopReason.APP_INTERRUPTED,
                    )
                self._repository.add(record)
                imported += 1
            except (
                HistoryProjectionError,
                OSError,
                TrajectoryCorruptionError,
                ValueError,
            ):
                failed += 1
                if temporary is not None:
                    temporary.unlink(missing_ok=True)
        return ImportResult(imported=imported, skipped=skipped, failed=failed)
