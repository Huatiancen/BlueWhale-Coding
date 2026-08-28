from __future__ import annotations

import asyncio
from pathlib import Path

import httpx
import pytest

from bluewhale_agent.domain.models import Action, ModelResponse
from bluewhale_agent.web.app import create_app
from bluewhale_agent.web.approvals import (
    ApprovalBroker,
    ApprovalConflictError,
    ApprovalDecision,
    ApprovalNotFoundError,
    ApprovalStatus,
)
from tests.fakes import FakeModelProvider


def overwrite_action() -> Action:
    return Action(
        id="overwrite-1",
        tool_name="write_file",
        arguments={"path": "existing.py", "content": "new\n"},
    )


@pytest.mark.asyncio
async def test_broker_resolves_an_approval_exactly_once() -> None:
    broker = ApprovalBroker(timeout_seconds=1)
    waiting = asyncio.create_task(
        broker.request("run-one", overwrite_action(), "Overwrite requires approval")
    )
    approval = await wait_for_pending(broker, "run-one")

    resolved = broker.resolve("run-one", approval.id, ApprovalDecision.APPROVE)

    assert await waiting is True
    assert resolved.status is ApprovalStatus.APPROVED
    with pytest.raises(ApprovalConflictError):
        broker.resolve("run-one", approval.id, ApprovalDecision.DENY)


@pytest.mark.asyncio
async def test_broker_times_out_to_denial_and_rejects_unknown_ids() -> None:
    broker = ApprovalBroker(timeout_seconds=0.01)

    assert await broker.request("run-one", overwrite_action(), "Risk") is False
    expired = broker.list_for_run("run-one")[0]
    assert expired.status is ApprovalStatus.EXPIRED
    with pytest.raises(ApprovalConflictError):
        broker.resolve("run-one", expired.id, ApprovalDecision.APPROVE)
    with pytest.raises(ApprovalNotFoundError):
        broker.resolve("run-one", "missing", ApprovalDecision.APPROVE)


@pytest.mark.asyncio
async def test_cancelling_a_run_cancels_its_pending_future() -> None:
    broker = ApprovalBroker(timeout_seconds=1)
    waiting = asyncio.create_task(broker.request("run-one", overwrite_action(), "Risk"))
    approval = await wait_for_pending(broker, "run-one")

    broker.cancel_run("run-one")

    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert broker.get("run-one", approval.id).status is ApprovalStatus.CANCELLED


@pytest.mark.asyncio
async def test_api_approval_executes_the_asked_action_once(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("old\n", encoding="utf-8")
    provider = FakeModelProvider(
        [
            ModelResponse(tool_calls=(overwrite_action(),), finish_reason="tool_calls"),
            ModelResponse(content="Updated safely.", finish_reason="stop"),
        ]
    )
    app = create_app(workspace=tmp_path, provider_factory=lambda: provider)
    async with app_client(app) as client:
        created = await client.post(
            "/api/runs",
            json={
                "run_id": "approved",
                "task": "Update existing.py",
                "permission_mode": "ask",
            },
        )
        approval = await wait_for_pending(app.state.approvals, "approved")
        pending_run = await client.get("/api/runs/approved")

        approved = await client.post(
            f"/api/runs/approved/approvals/{approval.id}",
            json={"decision": "approve"},
        )
        finished = await wait_for_terminal(client, "approved")
        repeated = await client.post(
            f"/api/runs/approved/approvals/{approval.id}",
            json={"decision": "deny"},
        )

    events = app.state.sessions.get("approved").trajectory.events_after(0)
    observations = [event for event in events if event.event.kind == "observation_received"]
    assert created.status_code == 202
    assert pending_run.json()["status"] == "waiting_approval"
    assert approved.status_code == 200
    assert approved.json()["status"] == "approved"
    assert repeated.status_code == 409
    assert finished["status"] == "completed"
    assert target.read_text(encoding="utf-8") == "new\n"
    assert len(observations) == 1
    assert {event.event.kind for event in events} >= {
        "approval_requested",
        "approval_resolved",
    }


@pytest.mark.asyncio
async def test_api_denial_unknown_approval_and_stop_are_safe(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("old\n", encoding="utf-8")
    provider = FakeModelProvider(
        [ModelResponse(tool_calls=(overwrite_action(),), finish_reason="tool_calls")]
    )
    app = create_app(workspace=tmp_path, provider_factory=lambda: provider)
    async with app_client(app) as client:
        await client.post(
            "/api/runs",
            json={"run_id": "denied", "task": "Overwrite", "permission_mode": "ask"},
        )
        approval = await wait_for_pending(app.state.approvals, "denied")
        unknown = await client.post(
            "/api/runs/denied/approvals/missing", json={"decision": "approve"}
        )
        invalid = await client.post(
            f"/api/runs/denied/approvals/{approval.id}",
            json={"decision": "always", "remember": True},
        )
        denied = await client.post(
            f"/api/runs/denied/approvals/{approval.id}", json={"decision": "deny"}
        )
        finished = await wait_for_terminal(client, "denied")

    assert unknown.status_code == 404
    assert invalid.status_code == 422
    assert denied.status_code == 200
    assert finished["status"] == "stopped"
    assert finished["stop_reason"] == "permission_denied"
    assert target.read_text(encoding="utf-8") == "old\n"

    blocking = FakeModelProvider(
        [ModelResponse(tool_calls=(overwrite_action(),), finish_reason="tool_calls")]
    )
    stop_app = create_app(workspace=tmp_path, provider_factory=lambda: blocking)
    async with app_client(stop_app) as client:
        await client.post(
            "/api/runs",
            json={"run_id": "stopped", "task": "Overwrite", "permission_mode": "ask"},
        )
        stopped_approval = await wait_for_pending(stop_app.state.approvals, "stopped")
        stopped = await client.post("/api/runs/stopped/stop")

    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert (
        stop_app.state.approvals.get("stopped", stopped_approval.id).status
        is ApprovalStatus.CANCELLED
    )


@pytest.mark.asyncio
async def test_balanced_mode_overwrites_without_approval(tmp_path: Path) -> None:
    target = tmp_path / "existing.py"
    target.write_text("old\n", encoding="utf-8")
    provider = FakeModelProvider(
        [
            ModelResponse(tool_calls=(overwrite_action(),), finish_reason="tool_calls"),
            ModelResponse(content="Updated.", finish_reason="stop"),
        ]
    )
    app = create_app(workspace=tmp_path, provider_factory=lambda: provider)

    async with app_client(app) as client:
        created = await client.post(
            "/api/runs",
            json={
                "run_id": "balanced",
                "task": "Overwrite",
                "permission_mode": "balanced",
            },
        )
        finished = await wait_for_terminal(client, "balanced")

    assert created.status_code == 202
    assert finished["status"] == "completed"
    assert target.read_text(encoding="utf-8") == "new\n"
    assert app.state.approvals.list_for_run("balanced") == ()


async def wait_for_pending(broker: ApprovalBroker, run_id: str):
    for _ in range(100):
        pending = broker.pending_for_run(run_id)
        if pending:
            return pending[0]
        await asyncio.sleep(0.01)
    raise AssertionError(f"approval did not become pending: {run_id}")


async def wait_for_terminal(client: httpx.AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = await client.get(f"/api/runs/{run_id}")
        body = response.json()
        if body["status"] in {"completed", "failed", "stopped"}:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"run did not finish: {run_id}")


def app_client(app) -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


def test_gui_exposes_safe_approval_and_stop_controls() -> None:
    static = Path(__file__).resolve().parents[2] / "src" / "bluewhale_agent" / "web" / "static"
    api = static.joinpath("js/api.js").read_text(encoding="utf-8")
    app = static.joinpath("js/app.js").read_text(encoding="utf-8")
    render = static.joinpath("js/render.js").read_text(encoding="utf-8")
    store = static.joinpath("js/store.js").read_text(encoding="utf-8")
    styles = static.joinpath("styles.css").read_text(encoding="utf-8")

    assert '"approval_requested"' in api
    assert '"approval_resolved"' in api
    assert "resolveApproval" in api
    assert "/approvals/" in api
    assert 'window.confirm("确定要停止当前任务吗？")' in app
    assert 'setConnectionState("stopping")' in app
    assert "onResolveApproval" in render
    assert "approval-card" in render
    assert "approval-actions" in render
    assert "impact_paths" in render
    assert "scrollHeight" in render
    assert 'storedEvent.event.kind === "state_changed"' in store
    assert "storedEvent.event.payload.status" in store
    assert "innerHTML" not in render
    assert ".approval-card" in styles
    assert ".approval-actions" in styles
