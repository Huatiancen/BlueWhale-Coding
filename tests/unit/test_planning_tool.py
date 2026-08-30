from __future__ import annotations

from pathlib import Path

import pytest

from bluewhale_agent.evidence.ledger import EvidenceLedger, StepStatus
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.tools.base import ToolContext
from bluewhale_agent.tools.planning import UpdatePlanTool


@pytest.mark.asyncio
async def test_update_plan_creates_evidence_requirements_and_active_step(
    tmp_path: Path,
) -> None:
    ledger = EvidenceLedger()
    tool = UpdatePlanTool(ledger)

    output = await tool.invoke(
        {
            "steps": [
                {
                    "id": "inspect",
                    "description": "定位实现入口",
                    "requirement": "locate",
                },
                {
                    "id": "change",
                    "description": "实现修改",
                    "requirement": "modify",
                },
            ],
            "active_step_id": "inspect",
        },
        ToolContext(paths=WorkspacePaths(tmp_path)),
    )

    assert output.metadata["active_step_id"] == "inspect"
    assert [step.status for step in ledger.steps] == [
        StepStatus.RUNNING,
        StepStatus.PENDING,
    ]


@pytest.mark.asyncio
async def test_update_plan_preserves_completed_steps(tmp_path: Path) -> None:
    ledger = EvidenceLedger()
    ledger.add_step("inspect", "定位实现入口", "locate")
    ledger.mark_running("inspect")
    tool = UpdatePlanTool(ledger)

    await tool.invoke(
        {
            "steps": [
                {
                    "id": "inspect",
                    "description": "定位实现入口",
                    "requirement": "locate",
                },
                {
                    "id": "change",
                    "description": "实现修改",
                    "requirement": "modify",
                },
            ],
            "active_step_id": "inspect",
        },
        ToolContext(paths=WorkspacePaths(tmp_path)),
    )

    assert ledger.get_step("inspect").status is StepStatus.RUNNING
