"""Lifecycle state machine for one BlueWhale run."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.domain.models import Limits, RunStatus, StopReason


class InvalidTransition(RuntimeError):
    """Raised when a lifecycle method is called from the wrong state."""


class AgentState(BaseModel):
    """Mutable, validated state owned by the future session controller."""

    model_config = ConfigDict(validate_assignment=True)

    task: str = Field(min_length=1)
    limits: Limits
    status: RunStatus = RunStatus.INITIALIZING
    steps_taken: int = Field(default=0, ge=0)
    repair_attempts: int = Field(default=0, ge=0)
    verified: bool | None = None
    stop_reason: StopReason | None = None

    @classmethod
    def start(cls, task: str, limits: Limits | None = None) -> AgentState:
        """Create a new run in its initializing state."""
        return cls(task=task, limits=limits or Limits())

    @property
    def can_continue(self) -> bool:
        """Return whether the controller may execute another loop step."""
        return self.status not in {
            RunStatus.COMPLETED,
            RunStatus.FAILED,
            RunStatus.STOPPED,
        }

    def mark_running(self) -> None:
        """Move a newly initialized run into its execution loop."""
        self._require_status(RunStatus.INITIALIZING, RunStatus.RUNNING)
        self.status = RunStatus.RUNNING

    def begin_verification(self) -> None:
        """Move an executing run into verification."""
        self._require_status(RunStatus.RUNNING, RunStatus.VERIFYING)
        self.status = RunStatus.VERIFYING

    def complete(self, *, verified: bool) -> None:
        """Finish verification or return the run for one repair attempt."""
        target = RunStatus.COMPLETED if verified else RunStatus.RUNNING
        self._require_status(RunStatus.VERIFYING, target)
        self.verified = verified
        if verified:
            self.status = RunStatus.COMPLETED
            self.stop_reason = StopReason.COMPLETED
            return

        self.repair_attempts += 1
        self.status = RunStatus.RUNNING

    def record_step(self) -> None:
        """Record one execution step and stop when its budget is exhausted."""
        self._require_status(RunStatus.RUNNING, RunStatus.RUNNING)
        self.steps_taken += 1
        if self.steps_taken >= self.limits.max_steps:
            self.status = RunStatus.STOPPED
            self.stop_reason = StopReason.STEP_LIMIT

    def _require_status(self, expected: RunStatus, target: RunStatus) -> None:
        if self.status is not expected:
            raise InvalidTransition(
                f"Cannot transition from {self.status.name} to {target.name}; "
                f"expected {expected.name}."
            )

