"""SQLite index for locally persisted BlueWhale runs."""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from bluewhale_agent.domain.models import RunStatus, StopReason

_ACTIVE_STATUSES = (
    RunStatus.INITIALIZING,
    RunStatus.RUNNING,
    RunStatus.WAITING_APPROVAL,
    RunStatus.VERIFYING,
)


class HistoryConflictError(RuntimeError):
    """Raised when a history run id already exists."""


@dataclass(frozen=True, slots=True)
class HistoryRecord:
    """One queryable summary whose full events remain in JSONL."""

    id: str
    task: str
    workspace: Path
    workspace_name: str
    status: RunStatus
    stop_reason: StopReason | None
    verified: bool | None
    final_answer: str | None
    steps_taken: int
    repair_attempts: int
    created_at: datetime
    updated_at: datetime
    events_path: Path

    @property
    def workspace_available(self) -> bool:
        return self.workspace.is_dir()


class HistoryRepository:
    """Own the local history index without interpreting event payloads."""

    def __init__(self, root: Path) -> None:
        self.root = root.expanduser().resolve(strict=False)
        self.database_path = self.root / "history.sqlite3"
        self.runs_root = self.root / "runs"
        self._lock = Lock()
        self.runs_root.mkdir(parents=True, exist_ok=True)
        self._initialize()

    def add(self, record: HistoryRecord) -> None:
        values = self._record_values(record)
        try:
            with self._lock, self._connect() as connection:
                connection.execute(
                    """
                    INSERT INTO runs (
                        id, task, workspace_path, workspace_name, status, stop_reason,
                        verified, final_answer, steps_taken, repair_attempts,
                        created_at, updated_at, events_path, schema_version
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
                    """,
                    values,
                )
        except sqlite3.IntegrityError as error:
            raise HistoryConflictError(f"History run already exists: {record.id}") from error

    def update(self, record: HistoryRecord) -> None:
        values = self._record_values(record)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                """
                UPDATE runs SET
                    task = ?, workspace_path = ?, workspace_name = ?, status = ?,
                    stop_reason = ?, verified = ?, final_answer = ?, steps_taken = ?,
                    repair_attempts = ?, created_at = ?, updated_at = ?, events_path = ?
                WHERE id = ?
                """,
                (*values[1:], values[0]),
            )
            if cursor.rowcount != 1:
                raise KeyError(record.id)

    def get(self, run_id: str) -> HistoryRecord | None:
        with self._lock, self._connect() as connection:
            row = connection.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        return self._from_row(row) if row is not None else None

    def contains(self, run_id: str) -> bool:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT 1 FROM runs WHERE id = ? LIMIT 1", (run_id,)
            ).fetchone()
        return row is not None

    def list(self) -> tuple[HistoryRecord, ...]:
        with self._lock, self._connect() as connection:
            rows = connection.execute(
                "SELECT * FROM runs ORDER BY updated_at DESC, id DESC"
            ).fetchall()
        return tuple(self._from_row(row) for row in rows)

    def recover_interrupted(self, recovered_at: datetime | None = None) -> int:
        timestamp = recovered_at or datetime.now(UTC)
        statuses = tuple(status.value for status in _ACTIVE_STATUSES)
        placeholders = ", ".join("?" for _ in statuses)
        with self._lock, self._connect() as connection:
            cursor = connection.execute(
                f"""
                UPDATE runs
                SET status = ?, stop_reason = ?, updated_at = ?
                WHERE status IN ({placeholders})
                """,
                (
                    RunStatus.STOPPED.value,
                    StopReason.APP_INTERRUPTED.value,
                    timestamp.isoformat(),
                    *statuses,
                ),
            )
            return cursor.rowcount

    def _initialize(self) -> None:
        self.root.mkdir(parents=True, exist_ok=True)
        with self._lock, self._connect() as connection:
            connection.execute("PRAGMA journal_mode = WAL")
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS runs (
                    id TEXT PRIMARY KEY,
                    task TEXT NOT NULL,
                    workspace_path TEXT NOT NULL,
                    workspace_name TEXT NOT NULL,
                    status TEXT NOT NULL,
                    stop_reason TEXT,
                    verified INTEGER,
                    final_answer TEXT,
                    steps_taken INTEGER NOT NULL,
                    repair_attempts INTEGER NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    events_path TEXT NOT NULL,
                    schema_version INTEGER NOT NULL
                )
                """
            )
            connection.execute(
                "CREATE INDEX IF NOT EXISTS runs_updated_at ON runs(updated_at DESC)"
            )

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.database_path, timeout=5)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    def _record_values(self, record: HistoryRecord) -> tuple[object, ...]:
        try:
            relative_events = record.events_path.resolve(strict=False).relative_to(self.root)
        except ValueError as error:
            raise ValueError("events_path must stay inside the history root") from error
        verified = None if record.verified is None else int(record.verified)
        return (
            record.id,
            record.task,
            str(record.workspace),
            record.workspace_name,
            record.status.value,
            record.stop_reason.value if record.stop_reason is not None else None,
            verified,
            record.final_answer,
            record.steps_taken,
            record.repair_attempts,
            record.created_at.isoformat(),
            record.updated_at.isoformat(),
            str(relative_events),
        )

    def _from_row(self, row: sqlite3.Row) -> HistoryRecord:
        verified_value = row["verified"]
        return HistoryRecord(
            id=str(row["id"]),
            task=str(row["task"]),
            workspace=Path(str(row["workspace_path"])),
            workspace_name=str(row["workspace_name"]),
            status=RunStatus(str(row["status"])),
            stop_reason=(
                StopReason(str(row["stop_reason"])) if row["stop_reason"] is not None else None
            ),
            verified=None if verified_value is None else bool(verified_value),
            final_answer=(str(row["final_answer"]) if row["final_answer"] is not None else None),
            steps_taken=int(row["steps_taken"]),
            repair_attempts=int(row["repair_attempts"]),
            created_at=datetime.fromisoformat(str(row["created_at"])),
            updated_at=datetime.fromisoformat(str(row["updated_at"])),
            events_path=self.root / str(row["events_path"]),
        )
