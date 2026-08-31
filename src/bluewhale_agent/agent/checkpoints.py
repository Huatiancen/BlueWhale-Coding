"""Durable, redacted checkpoints for safely resuming one agent run."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bluewhale_agent.domain.models import Action, Message
from bluewhale_agent.trajectory.redaction import redact

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class CheckpointPhase(StrEnum):
    PREPARING = "preparing"
    MODEL_REQUEST = "model_request"
    MODEL_RESPONSE = "model_response"
    TOOL_EXECUTING = "tool_executing"
    TOOL_FINISHED = "tool_finished"
    WAITING_APPROVAL = "waiting_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    INTERRUPTED = "interrupted"
    FAILED = "failed"


class RunCheckpoint(BaseModel):
    """Minimal state required to decide how a stopped run may resume."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    run_id: str = Field(min_length=1)
    task: str | None = None
    phase: CheckpointPhase
    messages: tuple[Message, ...] = ()
    pending_action: Action | None = None
    completed_action_ids: tuple[str, ...] = ()
    active_skill_names: tuple[str, ...] = ()
    changeset_id: str | None = None
    recorded_at: datetime = Field(default_factory=lambda: datetime.now(UTC))

    @property
    def needs_reconciliation(self) -> bool:
        return (
            self.phase is CheckpointPhase.TOOL_EXECUTING
            and self.pending_action is not None
            and self.pending_action.id not in self.completed_action_ids
        )


class RunCheckpointStore:
    """Atomically persist the latest resumable checkpoint for a run."""

    def __init__(
        self,
        workspace: Path,
        run_id: str,
        *,
        runs_root: Path | None = None,
    ) -> None:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ValueError(f"Invalid run id: {run_id!r}")
        selected_root = runs_root or workspace.resolve() / ".bluewhale" / "runs"
        self.path = selected_root.resolve(strict=False) / run_id / "checkpoint.json"
        self._lock = Lock()

    def save(self, checkpoint: RunCheckpoint) -> RunCheckpoint:
        if checkpoint.run_id != self.path.parent.name:
            raise ValueError("Checkpoint run id does not match its store")
        sanitized = RunCheckpoint.model_validate(redact(checkpoint.model_dump(mode="json")))
        temporary = self.path.with_suffix(".tmp")
        with self._lock:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            with temporary.open("w", encoding="utf-8") as stream:
                stream.write(sanitized.model_dump_json())
                stream.flush()
                os.fsync(stream.fileno())
            temporary.replace(self.path)
        return sanitized

    def load_latest(self) -> RunCheckpoint | None:
        with self._lock:
            if not self.path.is_file():
                return None
            try:
                return RunCheckpoint.model_validate_json(self.path.read_text(encoding="utf-8"))
            except (OSError, UnicodeError, ValidationError, ValueError):
                quarantine = self.path.with_name("checkpoint.corrupt.json")
                if quarantine.exists():
                    quarantine.unlink()
                self.path.replace(quarantine)
                return None
