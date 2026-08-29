"""Project durable run events into a queryable history summary."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from bluewhale_agent.domain.events import EventKind
from bluewhale_agent.domain.models import RunStatus, StopReason
from bluewhale_agent.history.repository import HistoryRecord
from bluewhale_agent.trajectory.store import StoredEvent


class HistoryProjectionError(ValueError):
    """Raised when required identity data cannot be recovered from events."""


def project_history(
    run_id: str,
    workspace: Path,
    events_path: Path,
    events: list[StoredEvent],
) -> HistoryRecord:
    """Build a tolerant summary from one ordered event trajectory."""
    started = next((item for item in events if item.event.kind is EventKind.RUN_STARTED), None)
    task = started.event.payload.get("task") if started is not None else None
    if not isinstance(task, str) or not task.strip():
        raise HistoryProjectionError("trajectory has no valid run_started task")

    status = RunStatus.INITIALIZING
    stop_reason: StopReason | None = None
    verified: bool | None = None
    final_answer: str | None = None
    steps_taken = 0
    repair_attempts = 0

    for stored in events:
        payload = stored.event.payload
        if stored.event.kind is EventKind.STATE_CHANGED:
            status = _enum_value(RunStatus, payload.get("status"), status)
            steps_taken = _non_negative_int(payload.get("steps_taken"), steps_taken)
            repair_attempts = _non_negative_int(
                payload.get("repair_attempts"), repair_attempts
            )
        elif stored.event.kind is EventKind.VERIFICATION_FINISHED:
            outcome = payload.get("outcome")
            if isinstance(outcome, dict) and isinstance(outcome.get("passed"), bool):
                verified = outcome["passed"]
        elif stored.event.kind is EventKind.RUN_FINISHED:
            status = _enum_value(RunStatus, payload.get("status"), status)
            stop_reason = _optional_enum(StopReason, payload.get("stop_reason"))
            if isinstance(payload.get("verified"), bool):
                verified = payload["verified"]  # type: ignore[assignment]
            if isinstance(payload.get("final_answer"), str):
                final_answer = payload["final_answer"]  # type: ignore[assignment]

    resolved_workspace = workspace.resolve(strict=False)
    return HistoryRecord(
        id=run_id,
        task=task,
        workspace=resolved_workspace,
        workspace_name=resolved_workspace.name or str(resolved_workspace),
        status=status,
        stop_reason=stop_reason,
        verified=verified,
        final_answer=final_answer,
        steps_taken=steps_taken,
        repair_attempts=repair_attempts,
        created_at=events[0].recorded_at,
        updated_at=events[-1].recorded_at,
        events_path=events_path,
    )


def _enum_value(enum_type: type[Any], value: object, fallback: Any) -> Any:
    if not isinstance(value, str):
        return fallback
    try:
        return enum_type(value)
    except ValueError:
        return fallback


def _optional_enum(enum_type: type[Any], value: object) -> Any | None:
    if not isinstance(value, str):
        return None
    try:
        return enum_type(value)
    except ValueError:
        return None


def _non_negative_int(value: object, fallback: int) -> int:
    if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
        return value
    return fallback
