"""Validated HTTP request and response contracts."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.domain.models import RunStatus, StopReason
from bluewhale_agent.runtime.permissions import PermissionMode
from bluewhale_agent.web.approvals import ApprovalDecision


class HealthResponse(BaseModel):
    status: str = "ok"


class WorkspaceFileResponse(BaseModel):
    """A text artifact read from the workspace associated with one run."""

    model_config = ConfigDict(frozen=True)

    path: str
    content: str
    mime_type: str
    size: int = Field(ge=0)


class RunCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    run_id: str | None = Field(
        default=None,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$",
    )
    workspace: str | None = Field(default=None, min_length=1)
    workspace_grant_id: str | None = Field(default=None, min_length=1)
    permission_mode: PermissionMode = PermissionMode.BALANCED


class RunContinueRequest(BaseModel):
    """A new user turn appended to an existing local run trajectory."""

    model_config = ConfigDict(extra="forbid")

    task: str = Field(min_length=1)
    workspace: str | None = Field(default=None, min_length=1)
    workspace_grant_id: str | None = Field(default=None, min_length=1)
    permission_mode: PermissionMode = PermissionMode.BALANCED


class RuntimeInstructionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    content: str = Field(min_length=1, max_length=20_000)


class FileUndoRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    paths: tuple[str, ...] = Field(min_length=1)


class ApprovalResolveRequest(BaseModel):
    """Strict one-shot decision submitted by the local GUI."""

    model_config = ConfigDict(extra="forbid")

    decision: ApprovalDecision


class RunResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    task: str
    workspace: str
    workspace_name: str
    workspace_available: bool = True
    historical: bool = False
    continuable: bool = False
    status: RunStatus
    stop_reason: StopReason | None = None
    verified: bool | None = None
    final_answer: str | None = None
    steps_taken: int = Field(default=0, ge=0)
    repair_attempts: int = Field(default=0, ge=0)
    created_at: datetime
