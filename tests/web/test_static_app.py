from __future__ import annotations

import re
import tomllib
from pathlib import Path

import httpx
import pytest

from bluewhale_agent.domain.models import ModelResponse
from bluewhale_agent.web.app import create_app
from tests.fakes import FakeModelProvider


@pytest.mark.asyncio
async def test_root_serves_accessible_four_region_workspace(tmp_path: Path) -> None:
    async with app_client(tmp_path) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    html = response.text
    assert 'id="task-form"' in html
    assert 'for="task-input"' in html
    assert 'id="session-list"' in html
    assert 'id="conversation-panel"' in html
    assert 'id="activity-timeline"' in html
    assert 'id="changes-panel"' in html
    assert 'id="evidence-panel"' in html
    assert 'aria-live="polite"' in html
    assert 'href="#workspace-main"' in html
    assert 'type="module" src="/static/js/app.js"' in html
    assert re.search(r"https?://", html) is None


@pytest.mark.asyncio
async def test_static_assets_have_correct_types_and_unknown_asset_is_404(
    tmp_path: Path,
) -> None:
    async with app_client(tmp_path) as client:
        css = await client.get("/static/styles.css")
        javascript = await client.get("/static/js/app.js")
        missing = await client.get("/static/js/missing.js")

    assert css.status_code == 200
    assert css.headers["content-type"].startswith("text/css")
    assert javascript.status_code == 200
    assert "javascript" in javascript.headers["content-type"]
    assert missing.status_code == 404


def test_styles_define_bluewhale_palette_and_responsive_layout() -> None:
    css = static_root().joinpath("styles.css").read_text(encoding="utf-8")

    assert "--ocean-950" in css
    assert "--cyan-400" in css
    assert "--success" in css
    assert "--warning" in css
    assert "--danger" in css
    assert "grid-template-areas" in css
    assert "@media" in css
    assert "prefers-reduced-motion" in css
    assert "url(http" not in css


def test_frontend_uses_safe_dom_rendering_and_modular_state() -> None:
    scripts = {
        path.name: path.read_text(encoding="utf-8")
        for path in static_root().joinpath("js").glob("*.js")
    }
    combined = "\n".join(scripts.values())

    assert set(scripts) == {"api.js", "app.js", "render.js", "store.js"}
    assert "innerHTML" not in combined
    assert "insertAdjacentHTML" not in combined
    assert "document.write" not in combined
    assert "eval(" not in combined
    assert "textContent" in scripts["render.js"]
    assert "fetch(" in scripts["api.js"]
    assert "new EventSource" in scripts["api.js"]
    assert "runs:" in scripts["store.js"]
    assert "activeRunId:" in scripts["store.js"]
    assert "events:" in scripts["store.js"]
    assert "connectionState:" in scripts["store.js"]
    assert "selectedPanel:" in scripts["store.js"]
    for category in ("PLAN", "MODEL", "TOOL", "EDIT", "TEST", "ERROR", "DONE"):
        assert category in scripts["render.js"]


def test_static_assets_are_included_in_package_configuration() -> None:
    project_root = Path(__file__).resolve().parents[2]
    config = tomllib.loads((project_root / "pyproject.toml").read_text(encoding="utf-8"))

    package_data = config["tool"]["setuptools"]["package-data"]["bluewhale_agent"]
    assert set(package_data) == {"web/static/*", "web/static/js/*"}


def app_client(workspace: Path) -> httpx.AsyncClient:
    app = create_app(
        workspace=workspace,
        provider_factory=lambda: FakeModelProvider(
            [ModelResponse(content="done", finish_reason="stop")]
        ),
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://test",
    )


def static_root() -> Path:
    return Path(__file__).resolve().parents[2] / "src" / "bluewhale_agent" / "web" / "static"
