"""Provider-independent models used by the agent core."""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field


class RunStatus(StrEnum):
    """Lifecycle states for one agent run."""

    INITIALIZING = "initializing"
    RUNNING = "running"
    WAITING_APPROVAL = "waiting_approval"
    VERIFYING = "verifying"
    COMPLETED = "completed"
    FAILED = "failed"
    STOPPED = "stopped"


class StopReason(StrEnum):
    """Stable reasons why an agent run stopped."""

    COMPLETED = "completed"
    PARTIALLY_VERIFIED = "partially_verified"
    USER_STOPPED = "user_stopped"
    APP_INTERRUPTED = "app_interrupted"
    STEP_LIMIT = "step_limit"
    TIME_LIMIT = "time_limit"
    NO_PROGRESS = "no_progress"
    PERMISSION_DENIED = "permission_denied"
    MODEL_PROTOCOL_ERROR = "model_protocol_error"
    API_ERROR = "api_error"
    TOOL_ERROR = "tool_error"
    VERIFICATION_FAILED = "verification_failed"


class ObservationStatus(StrEnum):
    """Result categories returned by local tools."""

    SUCCESS = "success"
    ERROR = "error"
    DENIED = "denied"
    TIMEOUT = "timeout"


class MessageRole(StrEnum):
    """Roles supported by the model-neutral conversation history."""

    SYSTEM = "system"
    USER = "user"
    ASSISTANT = "assistant"
    TOOL = "tool"


class Limits(BaseModel):
    """Resource boundaries enforced by the agent controller."""

    model_config = ConfigDict(frozen=True)

    max_steps: int | None = Field(default=None, gt=0)
    max_wall_time_seconds: int | None = Field(default=None, gt=0)
    progress_check_interval: int = Field(default=20, gt=0)
    max_consecutive_format_errors: int = Field(default=3, gt=0)
    max_api_retries: int = Field(default=3, ge=0)
    max_repair_attempts: int = Field(default=3, ge=0)
    command_timeout_seconds: int = Field(default=120, gt=0)


class Action(BaseModel):
    """A validated request to invoke one local tool."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    tool_name: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    arguments: dict[str, object] = Field(default_factory=dict)
    requested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class Observation(BaseModel):
    """A provider-neutral result produced by a local tool."""

    model_config = ConfigDict(frozen=True)

    action_id: str = Field(min_length=1)
    status: ObservationStatus
    summary: str
    content: str = ""
    metadata: dict[str, object] = Field(default_factory=dict)
    duration_ms: int = Field(ge=0)


class Message(BaseModel):
    """One model-neutral conversation message."""

    model_config = ConfigDict(frozen=True)

    role: MessageRole
    content: str | None
    reasoning_content: str | None = None
    tool_call_id: str | None = None
    tool_calls: tuple[Action, ...] = ()


class ModelResponse(BaseModel):
    """The subset of a provider response consumed by the agent loop."""

    model_config = ConfigDict(frozen=True)

    content: str | None = None
    reasoning_content: str | None = None
    tool_calls: tuple[Action, ...] = ()
    finish_reason: str
