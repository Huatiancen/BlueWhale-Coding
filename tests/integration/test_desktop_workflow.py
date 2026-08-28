from __future__ import annotations

import asyncio
import os
import shutil
import sys
from pathlib import Path

import httpx
import pytest

from bluewhale_agent.desktop.grants import WorkspaceGrantRegistry
from bluewhale_agent.domain.models import Action, ModelResponse, RunStatus, StopReason
from bluewhale_agent.web.app import create_app
from bluewhale_agent.web.approvals import ApprovalStatus
from bluewhale_agent.web.schemas import RunCreateRequest
from bluewhale_agent.web.workspaces import GrantedWorkspaceResolver
from tests.fakes import FakeModelProvider

FIXTURE_ROOT = Path(__file__).resolve().parents[1] / "fixtures" / "sample_project"


@pytest.mark.asyncio
async def test_desktop_grant_completes_authenticated_coding_workflow(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    project = tmp_path / "sample_project"
    shutil.copytree(FIXTURE_ROOT, project)
    executable_directory = str(Path(sys.executable).parent)
    monkeypatch.setenv(
        "PATH",
        executable_directory + os.pathsep + os.environ.get("PATH", ""),
    )
    registry = WorkspaceGrantRegistry()
    grant = registry.grant(project)
    provider = FakeModelProvider(
        [
            ModelResponse(
                tool_calls=(
                    Action(
                        id="fix-zero",
                        tool_name="apply_patch",
                        arguments={
                            "path": "calculator.py",
                            "search": "    return dividend / divisor\n",
                            "replace": (
                                "    if divisor == 0:\n"
                                "        return None\n"
                                "    return dividend / divisor\n"
                            ),
                        },
                    ),
                ),
                finish_reason="tool_calls",
            ),
            ModelResponse(content="Fixed and verified.", finish_reason="stop"),
        ]
    )
    app = create_app(
        workspace_resolver=GrantedWorkspaceResolver(registry),
        provider_factory=lambda: provider,
        desktop_token="integration-launch-token",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        bootstrap = await client.get(
            "/desktop/bootstrap?token=integration-launch-token"
        )
        created = await client.post(
            "/api/runs",
            json={
                "task": "Fix division by zero",
                "workspace_grant_id": grant.id,
            },
        )
        finished = await wait_for_terminal(client, created.json()["id"])

    assert bootstrap.status_code == 200
    assert created.status_code == 202
    assert finished["status"] == "completed"
    assert finished["verified"] is True
    assert "if divisor == 0:" in (project / "calculator.py").read_text(encoding="utf-8")
    await app.state.sessions.shutdown()


@pytest.mark.asyncio
async def test_desktop_rejects_forged_grant_before_provider_creation(tmp_path: Path) -> None:
    registry = WorkspaceGrantRegistry()
    provider_created = False

    def provider_factory() -> FakeModelProvider:
        nonlocal provider_created
        provider_created = True
        return FakeModelProvider([])

    app = create_app(
        workspace_resolver=GrantedWorkspaceResolver(registry),
        provider_factory=provider_factory,
        desktop_token="integration-launch-token",
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=True,
    ) as client:
        await client.get("/desktop/bootstrap?token=integration-launch-token")
        response = await client.post(
            "/api/runs",
            json={"task": "Escape", "workspace_grant_id": "forged"},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "Unknown workspace grant"
    assert provider_created is False


@pytest.mark.asyncio
async def test_desktop_shutdown_cancels_active_run_and_pending_approval(
    tmp_path: Path,
) -> None:
    protected_file = tmp_path / "existing.txt"
    protected_file.write_text("original", encoding="utf-8")
    registry = WorkspaceGrantRegistry()
    grant = registry.grant(tmp_path)
    provider = FakeModelProvider(
        [
            ModelResponse(
                tool_calls=(
                    Action(
                        id="write-on-close",
                        tool_name="write_file",
                        arguments={"path": "existing.txt", "content": "should not be written"},
                    ),
                ),
                finish_reason="tool_calls",
            )
        ]
    )
    app = create_app(
        workspace_resolver=GrantedWorkspaceResolver(registry),
        provider_factory=lambda: provider,
    )
    session = await app.state.sessions.create(
        RunCreateRequest(task="Wait for approval", workspace_grant_id=grant.id)
    )

    for _ in range(100):
        pending = app.state.approvals.pending_for_run(session.id)
        if pending:
            break
        await asyncio.sleep(0.01)
    else:
        raise AssertionError("approval did not become pending")

    await app.state.sessions.shutdown()

    assert app.state.sessions.has_active_run() is False
    assert session.status is RunStatus.STOPPED
    assert session.result is not None
    assert session.result.stop_reason is StopReason.USER_STOPPED
    assert app.state.approvals.get(session.id, pending[0].id).status is ApprovalStatus.CANCELLED
    assert protected_file.read_text(encoding="utf-8") == "original"


async def wait_for_terminal(
    client: httpx.AsyncClient,
    run_id: str,
) -> dict[str, object]:
    for _ in range(100):
        response = await client.get(f"/api/runs/{run_id}")
        body = response.json()
        if body["status"] in {"completed", "failed", "stopped"}:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"desktop run did not finish: {run_id}")
