"""Validated HTTP request and response contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.domain.models import RunStatus, StopReason


class HealthResponse(BaseModel):
    status: str = "ok"


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
    )
    workspace: str = Field(default=".", min_length=1)


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    task: str
    workspace: str
    status: RunStatus
    stop_reason: StopReason | None = None
    verified: bool | None = None
    final_answer: str | None = None
    steps_taken: int = Field(default=0, ge=0)
    repair_attempts: int = Field(default=0, ge=0)
    created_at: datetime
