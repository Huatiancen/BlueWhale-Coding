from pathlib import Path

import httpx
import pytest

from bluewhale_agent.domain.models import ModelResponse
from bluewhale_agent.web.app import create_app
from tests.fakes import FakeModelProvider


@pytest.mark.asyncio
async def test_run_file_endpoint_reads_only_text_inside_the_bound_workspace(
    tmp_path: Path,
) -> None:
    (tmp_path / "notes.md").write_text("# Local preview\n", encoding="utf-8")
    app = create_app(
        workspace=tmp_path,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="done", finish_reason="stop")]
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post("/api/runs", json={"task": "read"})
        run_id = created.json()["id"]
        response = await client.get(f"/api/runs/{run_id}/files", params={"path": "notes.md"})

    assert response.status_code == 200
    assert response.json()["content"] == "# Local preview\n"
    assert response.json()["mime_type"] == "text/markdown"


@pytest.mark.asyncio
@pytest.mark.parametrize("path", ["../secret.txt", "/etc/passwd", ".env", ".git/config"])
async def test_run_file_endpoint_rejects_unsafe_paths(tmp_path: Path, path: str) -> None:
    app = create_app(
        workspace=tmp_path,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="done", finish_reason="stop")]
        ),
    )
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as client:
        created = await client.post("/api/runs", json={"task": "read"})
        run_id = created.json()["id"]
        response = await client.get(f"/api/runs/{run_id}/files", params={"path": path})

    assert response.status_code == 403
