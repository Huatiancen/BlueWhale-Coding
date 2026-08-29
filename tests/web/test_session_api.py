from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
import pytest_asyncio
from fastapi import FastAPI
from pydantic import ValidationError

from bluewhale_agent.domain.models import MessageRole, ModelResponse
from bluewhale_agent.runtime.permissions import PermissionMode
from bluewhale_agent.web.app import create_app
from bluewhale_agent.web.schemas import RunCreateRequest
from bluewhale_agent.web.sessions import SessionManager
from tests.fakes import FakeModelProvider


class BlockingProvider:
    def __init__(self) -> None:
        self.started = asyncio.Event()

    async def complete(
        self,
        _messages: list[object],
        _tools: list[dict[str, object]],
    ) -> ModelResponse:
        self.started.set()
        await asyncio.Event().wait()
        raise AssertionError("unreachable")


def test_run_create_request_defaults_to_balanced_permission() -> None:
    request = RunCreateRequest(task="Inspect")

    assert request.permission_mode is PermissionMode.BALANCED


def test_run_create_request_rejects_unknown_permission_mode() -> None:
    with pytest.raises(ValidationError):
        RunCreateRequest(task="Inspect", permission_mode="unknown")


@pytest.fixture
def completed_app(tmp_path: Path) -> FastAPI:
    return create_app(
        workspace=tmp_path,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="Inspection complete.", finish_reason="stop")]
        ),
    )


@pytest_asyncio.fixture
async def client(completed_app: FastAPI) -> AsyncIterator[httpx.AsyncClient]:
    transport = httpx.ASGITransport(app=completed_app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as value:
        yield value


@pytest.mark.asyncio
async def test_health_create_list_and_get_run(client: httpx.AsyncClient) -> None:
    health = await client.get("/api/health")
    created = await client.post(
        "/api/runs",
        json={"run_id": "run-one", "task": "Inspect this project", "workspace": "."},
    )
    finished = await wait_for_terminal(client, "run-one")
    listed = await client.get("/api/runs")
    fetched = await client.get("/api/runs/run-one")

    assert health.status_code == 200
    assert health.json() == {"status": "ok"}
    assert created.status_code == 202
    assert created.json()["id"] == "run-one"
    assert finished["status"] == "completed"
    assert finished["final_answer"] == "Inspection complete."
    assert [item["id"] for item in listed.json()] == ["run-one"]
    assert fetched.json() == finished


@pytest.mark.asyncio
async def test_duplicate_unknown_and_unsafe_workspace_have_stable_errors(
    client: httpx.AsyncClient,
) -> None:
    first = await client.post("/api/runs", json={"run_id": "same-id", "task": "First"})
    await wait_for_terminal(client, "same-id")
    duplicate = await client.post("/api/runs", json={"run_id": "same-id", "task": "Second"})
    unknown_get = await client.get("/api/runs/missing")
    unknown_stop = await client.post("/api/runs/missing/stop")
    unknown_events = await client.get("/api/runs/missing/events")
    unsafe = await client.post(
        "/api/runs", json={"run_id": "unsafe", "task": "Escape", "workspace": ".."}
    )
    protected = await client.post(
        "/api/runs",
        json={
            "run_id": "protected",
            "task": "Read trajectories",
            "workspace": ".bluewhale",
        },
    )

    assert first.status_code == 202
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"] == "Run already exists: same-id"
    assert unknown_get.status_code == 404
    assert unknown_stop.status_code == 404
    assert unknown_events.status_code == 404
    assert unsafe.status_code == 400
    assert unsafe.json()["detail"] == "Workspace must stay inside the configured root"
    assert protected.status_code == 400
    assert protected.json()["detail"] == "Workspace is protected"


@pytest.mark.asyncio
async def test_only_one_run_can_be_active_and_stop_is_persisted(tmp_path: Path) -> None:
    provider = BlockingProvider()
    app = create_app(workspace=tmp_path, provider_factory=lambda: provider)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        first = await client.post("/api/runs", json={"run_id": "active", "task": "Wait forever"})
        await asyncio.wait_for(provider.started.wait(), timeout=1)
        conflict = await client.post("/api/runs", json={"run_id": "other", "task": "Cannot start"})
        stopped = await client.post("/api/runs/active/stop")
        fetched = await client.get("/api/runs/active")

    assert first.status_code == 202
    assert conflict.status_code == 409
    assert conflict.json()["detail"] == "Another run is already active"
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "stopped"
    assert stopped.json()["stop_reason"] == "user_stopped"
    assert fetched.json() == stopped.json()


@pytest.mark.asyncio
async def test_sse_replays_events_after_last_event_id_without_duplicates(
    client: httpx.AsyncClient,
) -> None:
    await client.post("/api/runs", json={"run_id": "sse-run", "task": "Inspect events"})
    await wait_for_terminal(client, "sse-run")

    initial = await client.get("/api/runs/sse-run/events")
    initial_events = parse_sse(initial.text)
    resume_after = initial_events[-2]["id"]
    resumed = await client.get(
        "/api/runs/sse-run/events",
        headers={"Last-Event-ID": str(resume_after)},
    )
    resumed_events = parse_sse(resumed.text)

    assert initial.status_code == 200
    assert initial.headers["content-type"].startswith("text/event-stream")
    assert initial_events
    assert [item["id"] for item in initial_events] == sorted(
        {item["id"] for item in initial_events}
    )
    assert [item["id"] for item in resumed_events] == [initial_events[-1]["id"]]
    assert all(item["id"] > resume_after for item in resumed_events)
    assert all(item["event"] == item["data"]["event"]["kind"] for item in initial_events)


@pytest.mark.asyncio
async def test_invalid_last_event_id_is_rejected(client: httpx.AsyncClient) -> None:
    await client.post("/api/runs", json={"run_id": "cursor-run", "task": "Inspect events"})
    await wait_for_terminal(client, "cursor-run")

    response = await client.get(
        "/api/runs/cursor-run/events", headers={"Last-Event-ID": "not-a-number"}
    )

    assert response.status_code == 400
    assert response.json()["detail"] == "Last-Event-ID must be a non-negative integer"


@pytest.mark.asyncio
async def test_sse_heartbeat_is_not_written_to_trajectory(tmp_path: Path) -> None:
    provider = BlockingProvider()
    manager = SessionManager(
        workspace_root=tmp_path,
        provider_factory=lambda: provider,
        heartbeat_seconds=0.01,
    )
    session = await manager.create(RunCreateRequest(run_id="heartbeat", task="Wait for heartbeat"))
    await asyncio.wait_for(provider.started.wait(), timeout=1)
    existing = session.trajectory.events_after(0)
    stream = manager.stream_events("heartbeat", existing[-1].sequence)

    heartbeat = await asyncio.wait_for(anext(stream), timeout=1)

    assert heartbeat == ": heartbeat\n\n"
    assert session.trajectory.events_after(0) == existing
    await stream.aclose()
    await manager.stop("heartbeat")


@pytest.mark.asyncio
async def test_provider_configuration_error_is_reported_as_503(tmp_path: Path) -> None:
    def invalid_provider() -> FakeModelProvider:
        raise ValueError("DEEPSEEK_API_KEY is required")

    app = create_app(workspace=tmp_path, provider_factory=invalid_provider)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        response = await client.post("/api/runs", json={"task": "Inspect"})

    assert response.status_code == 503
    assert response.json()["detail"] == "DEEPSEEK_API_KEY is required"


@pytest.mark.asyncio
async def test_api_rejects_unknown_permission_mode(client: httpx.AsyncClient) -> None:
    response = await client.post(
        "/api/runs", json={"task": "Inspect", "permission_mode": "unknown"}
    )

    assert response.status_code == 422


@pytest.mark.asyncio
async def test_local_history_survives_app_restart_and_replays_events(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    history_root = tmp_path / "application-history"
    first_app = create_app(
        workspace=workspace,
        history_root=history_root,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="Persisted answer.", finish_reason="stop")]
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=first_app), base_url="http://test"
    ) as first_client:
        created = await first_client.post(
            "/api/runs",
            json={"run_id": "persisted", "task": "Remember this task", "workspace": "."},
        )
        await wait_for_terminal(first_client, "persisted")

    second_app = create_app(
        workspace=workspace,
        history_root=history_root,
        provider_factory=lambda: FakeModelProvider([]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=second_app), base_url="http://test"
    ) as second_client:
        listed = await second_client.get("/api/runs")
        fetched = await second_client.get("/api/runs/persisted")
        replayed = await second_client.get("/api/runs/persisted/events")

    assert created.status_code == 202
    assert [item["id"] for item in listed.json()] == ["persisted"]
    assert fetched.json()["historical"] is True
    assert fetched.json()["workspace_name"] == "workspace"
    assert fetched.json()["workspace_available"] is True
    assert fetched.json()["final_answer"] == "Persisted answer."
    assert [event["event"] for event in parse_sse(replayed.text)][-1] == "run_finished"


@pytest.mark.asyncio
async def test_historical_run_continues_with_same_id_and_restored_context(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    history_root = tmp_path / "application-history"
    first_app = create_app(
        workspace=workspace,
        history_root=history_root,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="第一轮回答。", finish_reason="stop")]
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=first_app), base_url="http://test"
    ) as first_client:
        await first_client.post(
            "/api/runs",
            json={"run_id": "continued", "task": "先检查项目", "workspace": "."},
        )
        await wait_for_terminal(first_client, "continued")

    second_provider = FakeModelProvider(
        [ModelResponse(content="第二轮回答。", finish_reason="stop")]
    )
    second_app = create_app(
        workspace=workspace,
        history_root=history_root,
        provider_factory=lambda: second_provider,
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=second_app), base_url="http://test"
    ) as second_client:
        continued = await second_client.post(
            "/api/runs/continued/continue",
            json={"task": "继续解释边界条件", "workspace": "."},
        )
        finished = await wait_for_terminal(second_client, "continued")
        listed = await second_client.get("/api/runs")
        replayed = await second_client.get("/api/runs/continued/events")

    assert continued.status_code == 202
    assert continued.json()["id"] == "continued"
    assert continued.json()["task"] == "先检查项目"
    assert continued.json()["historical"] is False
    assert finished["final_answer"] == "第二轮回答。"
    assert finished["continuable"] is True
    assert [item["id"] for item in listed.json()] == ["continued"]
    sent = second_provider.calls[0][0]
    assert any(
        message.role is MessageRole.USER and message.content == "先检查项目"
        for message in sent
    )
    assert any(
        message.role is MessageRole.ASSISTANT and message.content == "第一轮回答。"
        for message in sent
    )
    assert any("继续解释边界条件" in (message.content or "") for message in sent)
    event_names = [event["event"] for event in parse_sse(replayed.text)]
    assert event_names.count("run_started") == 2
    assert event_names.count("run_finished") == 2


@pytest.mark.asyncio
async def test_historical_run_cannot_continue_after_workspace_disappears(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    history_root = tmp_path / "application-history"
    first_app = create_app(
        workspace=workspace,
        history_root=history_root,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="已保存。", finish_reason="stop")]
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=first_app), base_url="http://test"
    ) as first_client:
        await first_client.post(
            "/api/runs",
            json={"run_id": "missing-to-continue", "task": "保存", "workspace": "."},
        )
        await wait_for_terminal(first_client, "missing-to-continue")
    workspace.rmdir()

    fallback = tmp_path / "fallback"
    fallback.mkdir()
    second_app = create_app(
        workspace=fallback,
        history_root=history_root,
        provider_factory=lambda: FakeModelProvider([]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=second_app), base_url="http://test"
    ) as second_client:
        response = await second_client.post(
            "/api/runs/missing-to-continue/continue",
            json={"task": "继续", "workspace": "."},
        )

    assert response.status_code == 400
    assert response.json()["detail"] == "历史任务的工作区当前不可用"


@pytest.mark.asyncio
async def test_history_remains_readable_when_workspace_is_missing(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    history_root = tmp_path / "application-history"
    first_app = create_app(
        workspace=workspace,
        history_root=history_root,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="Saved.", finish_reason="stop")]
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=first_app), base_url="http://test"
    ) as first_client:
        await first_client.post(
            "/api/runs",
            json={"run_id": "missing-workspace", "task": "Persist", "workspace": "."},
        )
        await wait_for_terminal(first_client, "missing-workspace")
    workspace.rmdir()

    fallback_workspace = tmp_path / "fallback"
    fallback_workspace.mkdir()
    second_app = create_app(
        workspace=fallback_workspace,
        history_root=history_root,
        provider_factory=lambda: FakeModelProvider([]),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=second_app), base_url="http://test"
    ) as second_client:
        fetched = await second_client.get("/api/runs/missing-workspace")

    assert fetched.status_code == 200
    assert fetched.json()["historical"] is True
    assert fetched.json()["workspace_available"] is False


async def wait_for_terminal(client: httpx.AsyncClient, run_id: str) -> dict[str, object]:
    for _ in range(100):
        response = await client.get(f"/api/runs/{run_id}")
        body = response.json()
        if body["status"] in {"completed", "failed", "stopped"}:
            return body
        await asyncio.sleep(0.01)
    raise AssertionError(f"run did not finish: {run_id}")


def parse_sse(body: str) -> list[dict[str, object]]:
    parsed: list[dict[str, object]] = []
    for block in body.strip().split("\n\n"):
        if not block or block.startswith(":"):
            continue
        fields = dict(line.split(": ", 1) for line in block.splitlines())
        parsed.append(
            {
                "id": int(fields["id"]),
                "event": fields["event"],
                "data": json.loads(fields["data"]),
            }
        )
    return parsed
