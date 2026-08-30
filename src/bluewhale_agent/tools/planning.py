"""Model-facing task planning backed by deterministic evidence state."""

from __future__ import annotations

from typing import cast

from pydantic import BaseModel, ConfigDict, Field, model_validator

from bluewhale_agent.evidence.ledger import (
    EvidenceLedger,
    StepRequirement,
    StepStatus,
    TaskStep,
)
from bluewhale_agent.tools.base import BaseTool, ToolContext, ToolOutput


class PlanStepArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(min_length=1, max_length=48, pattern=r"^[a-zA-Z0-9_-]+$")
    description: str = Field(min_length=1, max_length=240)
    requirement: StepRequirement


class UpdatePlanArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    steps: tuple[PlanStepArguments, ...] = Field(min_length=1, max_length=12)
    active_step_id: str | None = None

    @model_validator(mode="after")
    def active_step_must_exist(self) -> UpdatePlanArguments:
        identifiers = [step.id for step in self.steps]
        if len(set(identifiers)) != len(identifiers):
            raise ValueError("step ids must be unique")
        if self.active_step_id is not None and self.active_step_id not in identifiers:
            raise ValueError("active_step_id must identify one of the plan steps")
        return self


class UpdatePlanTool(BaseTool):
    """Publish a concise plan; only evidence may complete its steps."""

    name = "update_plan"
    description = (
        "Create or revise the task plan. Select evidence requirements for every step. "
        "Do not mark steps complete yourself; BlueWhale derives completion from tools."
    )
    arguments_model = UpdatePlanArguments

    def __init__(self, ledger: EvidenceLedger) -> None:
        self._ledger = ledger

    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        del context
        request = cast(UpdatePlanArguments, arguments)
        steps = tuple(
            TaskStep(
                id=item.id,
                description=item.description,
                requirement=item.requirement,
            )
            for item in request.steps
        )
        self._ledger.set_plan(steps)
        if request.active_step_id is not None:
            active = self._ledger.get_step(request.active_step_id)
            if active.status is StepStatus.PENDING:
                self._ledger.mark_running(active.id)
        serialized = [step.model_dump(mode="json") for step in self._ledger.steps]
        return ToolOutput(
            summary="Task plan updated",
            metadata={
                "steps": serialized,
                "active_step_id": request.active_step_id,
            },
        )
