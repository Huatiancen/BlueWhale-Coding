from __future__ import annotations

from pathlib import Path

import httpx
import pytest

from bluewhale_agent.domain.models import ModelResponse
from bluewhale_agent.web.app import create_app
from tests.fakes import FakeModelProvider


def desktop_app(workspace: Path):
    return create_app(
        workspace=workspace,
        desktop_token="launch-secret",
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="done", finish_reason="stop")]
        ),
    )


@pytest.mark.asyncio
async def test_bootstrap_establishes_http_only_desktop_session(tmp_path: Path) -> None:
    transport = httpx.ASGITransport(app=desktop_app(tmp_path))
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://test",
        follow_redirects=False,
    ) as client:
        health = await client.get("/api/health")
        denied = await client.get("/")
        rejected = await client.get("/desktop/bootstrap?token=wrong")
        bootstrap = await client.get("/desktop/bootstrap?token=launch-secret")
        allowed = await client.get("/")

    assert health.status_code == 200
    assert denied.status_code == 401
    assert rejected.status_code == 401
    assert "set-cookie" not in rejected.headers
    assert bootstrap.status_code == 303
    assert bootstrap.headers["location"].startswith("/?v=")
    cookie = bootstrap.headers["set-cookie"]
    assert "HttpOnly" in cookie
    assert "SameSite=strict" in cookie
    assert "launch-secret" not in cookie
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_desktop_api_requires_session_cookie(tmp_path: Path) -> None:
    app = desktop_app(tmp_path)
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as outsider:
        denied = await outsider.get("/api/runs")

    async with httpx.AsyncClient(transport=transport, base_url="http://test") as desktop:
        await desktop.get("/desktop/bootstrap?token=launch-secret")
        allowed = await desktop.get("/api/runs")

    assert denied.status_code == 401
    assert denied.json()["detail"] == "Desktop session required"
    assert allowed.status_code == 200


@pytest.mark.asyncio
async def test_server_mode_remains_unauthenticated(tmp_path: Path) -> None:
    app = create_app(
        workspace=tmp_path,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="done", finish_reason="stop")]
        ),
    )
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://test") as client:
        root = await client.get("/")
        runs = await client.get("/api/runs")

    assert root.status_code == 200
    assert runs.status_code == 200
