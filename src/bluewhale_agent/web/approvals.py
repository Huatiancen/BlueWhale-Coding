"""One-shot, timeout-safe approval coordination for local tool actions."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.domain.models import Action


class ApprovalDecision(StrEnum):
    """Decisions accepted by the approval API."""

    APPROVE = "approve"
    DENY = "deny"


class ApprovalStatus(StrEnum):
    """Stable lifecycle states exposed to clients and trajectory events."""

    PENDING = "pending"
    APPROVED = "approved"
    DENIED = "denied"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


class ApprovalRecord(BaseModel):
    """Serializable description of one approval request."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    run_id: str = Field(min_length=1)
    action: Action
    reason: str = Field(min_length=1)
    impact_paths: tuple[str, ...] = ()
    status: ApprovalStatus = ApprovalStatus.PENDING
    requested_at: datetime
    resolved_at: datetime | None = None


class ApprovalNotFoundError(KeyError):
    """Raised when an approval id is unknown for the selected run."""


class ApprovalConflictError(RuntimeError):
    """Raised when a terminal approval is resolved a second time."""


@dataclass
class _Entry:
    record: ApprovalRecord
    future: asyncio.Future[ApprovalDecision]


class ApprovalBroker:
    """Own pending approval futures without granting implicit permission."""

    def __init__(self, *, timeout_seconds: float | None = None) -> None:
        if timeout_seconds is not None and timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive")
        self.timeout_seconds = timeout_seconds
        self._entries: dict[str, _Entry] = {}

    async def request(
        self,
        run_id: str,
        action: Action,
        reason: str,
        *,
        on_pending: Callable[[ApprovalRecord], None] | None = None,
    ) -> bool:
        """Wait for one explicit decision, with an optional bounded timeout."""

        approval_id = uuid4().hex
        record = ApprovalRecord(
            id=approval_id,
            run_id=run_id,
            action=action,
            reason=reason,
            impact_paths=_impact_paths(action),
            requested_at=datetime.now(UTC),
        )
        future = asyncio.get_running_loop().create_future()
        entry = _Entry(record=record, future=future)
        self._entries[approval_id] = entry
        if on_pending is not None:
            on_pending(record)
        try:
            decision = await asyncio.wait_for(asyncio.shield(future), timeout=self.timeout_seconds)
        except TimeoutError:
            if entry.record.status is ApprovalStatus.PENDING:
                entry.record = _terminal_record(entry.record, ApprovalStatus.EXPIRED)
                future.cancel()
            return False
        except asyncio.CancelledError:
            if entry.record.status is ApprovalStatus.PENDING:
                entry.record = _terminal_record(entry.record, ApprovalStatus.CANCELLED)
                future.cancel()
            raise
        return decision is ApprovalDecision.APPROVE

    def resolve(
        self,
        run_id: str,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> ApprovalRecord:
        """Resolve a pending approval exactly once."""

        entry = self._entry_for(run_id, approval_id)
        if entry.record.status is not ApprovalStatus.PENDING:
            raise ApprovalConflictError(
                f"Approval is already {entry.record.status.value}: {approval_id}"
            )
        status = (
            ApprovalStatus.APPROVED
            if decision is ApprovalDecision.APPROVE
            else ApprovalStatus.DENIED
        )
        entry.record = _terminal_record(entry.record, status)
        entry.future.set_result(decision)
        return entry.record

    def cancel_run(self, run_id: str) -> None:
        """Cancel every unresolved future owned by a stopped run."""

        for entry in self._entries.values():
            if entry.record.run_id != run_id:
                continue
            if entry.record.status is not ApprovalStatus.PENDING:
                continue
            entry.record = _terminal_record(entry.record, ApprovalStatus.CANCELLED)
            entry.future.cancel()

    def get(self, run_id: str, approval_id: str) -> ApprovalRecord:
        return self._entry_for(run_id, approval_id).record

    def list_for_run(self, run_id: str) -> tuple[ApprovalRecord, ...]:
        return tuple(
            entry.record for entry in self._entries.values() if entry.record.run_id == run_id
        )

    def pending_for_run(self, run_id: str) -> tuple[ApprovalRecord, ...]:
        return tuple(
            record
            for record in self.list_for_run(run_id)
            if record.status is ApprovalStatus.PENDING
        )

    def _entry_for(self, run_id: str, approval_id: str) -> _Entry:
        entry = self._entries.get(approval_id)
        if entry is None or entry.record.run_id != run_id:
            raise ApprovalNotFoundError(approval_id)
        return entry


def _terminal_record(record: ApprovalRecord, status: ApprovalStatus) -> ApprovalRecord:
    return record.model_copy(update={"status": status, "resolved_at": datetime.now(UTC)})


def _impact_paths(action: Action) -> tuple[str, ...]:
    paths: list[str] = []
    for name in ("path", "source", "destination"):
        value = action.arguments.get(name)
        if isinstance(value, str) and value not in paths:
            paths.append(value)
    return tuple(paths)
