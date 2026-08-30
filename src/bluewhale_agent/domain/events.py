"""Versioned events emitted while an agent run progresses."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class EventKind(StrEnum):
    """Event categories consumed by persistence and the Web GUI."""

    RUN_STARTED = "run_started"
    STATE_CHANGED = "state_changed"
    MODEL_RESPONSE = "model_response"
    MODEL_DELTA = "model_delta"
    PLAN_UPDATED = "plan_updated"
    INSTRUCTION_QUEUED = "instruction_queued"
    INSTRUCTION_DELIVERED = "instruction_delivered"
    INSTRUCTION_WITHDRAWN = "instruction_withdrawn"
    ACTION_REQUESTED = "action_requested"
    APPROVAL_REQUESTED = "approval_requested"
    APPROVAL_RESOLVED = "approval_resolved"
    OBSERVATION_RECEIVED = "observation_received"
    VERIFICATION_FINISHED = "verification_finished"
    CHANGESET_RECORDED = "changeset_recorded"
    CHANGESET_REVERTED = "changeset_reverted"
    RUN_FINISHED = "run_finished"


class RunEvent(BaseModel):
    """A serializable event independent of storage and transport details."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    run_id: str = Field(min_length=1)
    kind: EventKind
    payload: dict[str, object] = Field(default_factory=dict)
    occurred_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    schema_version: int = Field(default=1, ge=1)
