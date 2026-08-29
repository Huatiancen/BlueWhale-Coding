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
async def test_root_serves_accessible_conversation_workspace(tmp_path: Path) -> None:
    async with app_client(tmp_path) as client:
        response = await client.get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert response.headers["cache-control"] == "no-store"
    html = response.text
    assert '<meta name="color-scheme" content="light">' in html
    assert 'id="task-form"' in html
    assert 'id="new-task"' in html
    assert 'aria-label="新建任务"' in html
    assert 'for="task-input"' in html
    assert 'id="session-list"' in html
    assert '<p class="sidebar-label">项目</p>' in html
    assert 'id="conversation-panel"' in html
    assert 'id="home-title"' in html
    assert 'id="home-subtitle"' in html
    assert 'id="home-open-project"' not in html
    assert 'id="home-recent-projects"' not in html
    assert 'id="conversation-header"' in html
    assert 'id="conversation-shell"' in html
    assert 'id="composer-shell"' in html
    assert 'id="approval-dock"' in html
    assert 'id="artifact-inspector"' in html
    assert 'id="inspector-content"' in html
    assert 'id="sidebar-resizer"' in html
    assert 'id="inspector-resizer"' in html
    assert html.count('role="separator"') == 2
    composer = html[html.index('id="composer-shell"') :]
    assert composer.index('id="app-notice"') < composer.index('id="approval-dock"')
    assert composer.index('id="approval-dock"') < composer.index('id="task-form"')
    assert 'id="work-details"' not in html
    assert 'id="activity-timeline"' not in html
    assert 'id="changes-panel"' not in html
    assert 'id="evidence-panel"' not in html
    assert ">Evidence<" not in html
    assert ">Changes<" not in html
    assert "TRAJECTORY" not in html
    assert 'aria-live="polite"' in html
    assert 'href="#workspace-main"' in html
    assert 'href="/static/styles.css?v=codex-ui-2"' in html
    assert 'type="module" src="/static/js/app.js?v=codex-ui-2"' in html
    assert 'id="open-project"' in html
    assert 'id="desktop-project"' in html
    assert 'id="permission-trigger"' in html
    assert 'id="permission-menu"' in html
    assert html.count("data-permission-mode=") == 3
    assert 'data-permission-mode="ask"' in html
    assert 'data-permission-mode="balanced"' in html
    assert 'data-permission-mode="full"' in html
    assert 'id="model-settings"' in html
    assert 'id="api-key-input"' in html
    assert 'type="password"' in html
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
    assert css.headers["cache-control"] == "no-store"
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
    assert ".conversation-shell" in css
    assert ".panel-resizer" in css
    assert "--inspector-width" in css
    assert ".composer-shell" in css
    assert ".approval-dock" in css
    assert ".approval-dock[hidden]" in css
    assert ".conversation-feed > .work-details" in css
    assert ".project-group" in css
    assert ".history-project-button" in css
    assert ".project-task-list" in css
    assert ".project-folder-icon" in css
    assert ".session-button.active" in css
    assert ".status-dot" not in css
    assert ".session-copy" not in css
    assert ".message-copy-button" in css
    assert ".message:hover > .message-copy-button" in css
    assert ".assistant-message > .message-copy-button" in css
    assert ".user-message > .message-copy-button" in css
    assert ".diff-line.addition" in css
    assert ".diff-line.deletion" in css
    assert ".diff-line.hunk" in css
    assert ".diff-line-number" in css
    assert "max-width: 1040px" in css
    assert "@media" in css
    assert "prefers-reduced-motion" in css
    assert "url(http" not in css

    workspace_rule = css_rule(css, ".workspace-main")
    conversation_rule = css_rule(css, ".conversation-shell")
    assert "grid-template-rows: minmax(0, 1fr)" in workspace_rule
    assert "min-height: 0" in conversation_rule
    assert "overflow: hidden" in conversation_rule


def test_frontend_uses_safe_dom_rendering_and_modular_state() -> None:
    scripts = {
        path.name: path.read_text(encoding="utf-8")
        for path in static_root().joinpath("js").glob("*.js")
    }
    combined = "\n".join(scripts.values())

    assert set(scripts) == {
        "api.js",
        "app.js",
        "artifact-view.js",
        "composer-keyboard.js",
        "conversation-turns.js",
        "desktop.js",
        "diff-view.js",
        "event-view.js",
        "home-prompt.js",
        "markdown.js",
        "message-copy.js",
        "panel-resize.js",
        "project-groups.js",
        "render.js",
        "store.js",
        "stream-guard.js",
        "stream-lifecycle.js",
    }
    assert "innerHTML" not in combined
    assert "insertAdjacentHTML" not in combined
    assert "document.write" not in combined
    assert "eval(" not in combined
    assert "textContent" in scripts["render.js"]
    assert "renderMarkdown" in scripts["render.js"]
    assert 'from "./message-copy.js"' in scripts["render.js"]
    assert 'from "./project-groups.js"' in scripts["render.js"]
    assert 'from "./conversation-turns.js"' in scripts["render.js"]
    assert 'from "./artifact-view.js"' in scripts["app.js"]
    assert 'from "./composer-keyboard.js"' in scripts["app.js"]
    assert 'from "./diff-view.js"' in scripts["artifact-view.js"]
    assert "changeset-card" in scripts["render.js"]
    assert "getRunFile" in scripts["app.js"]
    assert "homePrompt" in scripts["app.js"]
    assert "elements.runTitle.parentElement.hidden = !run" in scripts["render.js"]
    assert "elements.conversationHeader.hidden = !run" not in scripts["render.js"]
    assert "recent-project-card" not in scripts["render.js"]
    assert "conversationTimeline" in scripts["render.js"]
    assert "groupRunsByProject" in scripts["render.js"]
    assert "history-project-button" in scripts["render.js"]
    assert "project-task-list" in scripts["render.js"]
    assert 'setAttribute("aria-expanded"' in scripts["render.js"]
    assert 'setAttribute("aria-current", "true")' in scripts["render.js"]
    assert "status-dot" not in scripts["render.js"]
    assert "session-copy" not in scripts["render.js"]
    assert "createMessageCopyButton(entry.content" in scripts["render.js"]
    assert '"撤销"' in scripts["render.js"]
    assert '"审核"' not in scripts["render.js"]
    assert "createElement" in scripts["markdown.js"]
    assert "fetch(" in scripts["api.js"]
    assert "new EventSource" in scripts["api.js"]
    assert "workspace_grant_id" in scripts["api.js"]
    assert "pywebviewready" in scripts["desktop.js"]
    assert "activate_history_workspace" in scripts["desktop.js"]
    assert "localStorage" not in scripts["desktop.js"]
    assert "sessionStorage" not in scripts["desktop.js"]
    assert "runs:" in scripts["store.js"]
    assert "activeRunId:" in scripts["store.js"]
    assert "events:" in scripts["store.js"]
    assert "connectionState:" in scripts["store.js"]
    assert 'permissionMode: "balanced"' in scripts["store.js"]
    assert "setPermissionMode" in scripts["store.js"]
    assert "permission_mode" in scripts["api.js"]
    assert "export function continueRun" in scripts["api.js"]
    assert "/continue`" in scripts["api.js"]
    assert "continueRun" in scripts["app.js"]
    assert "selectedRun" in scripts["app.js"]
    assert "if (desktopBridge && selectedRun?.continuable)" in scripts["app.js"]
    assert "desktopBridge && !workspaceGrantId && selectedRun?.continuable" not in scripts["app.js"]
    assert "startNewTask" in scripts["app.js"]
    assert "selectRun(null)" in scripts["app.js"]
    assert "ensureRunWorkspace" in scripts["app.js"]
    assert 'from "./stream-guard.js"' in scripts["app.js"]
    assert 'from "./stream-lifecycle.js"' in scripts["app.js"]
    assert "isCurrentStream" in scripts["app.js"]
    assert "if (state.activeRunId) connectToRun" not in scripts["app.js"]
    assert "permissionMode" in scripts["app.js"]
    assert "onCopyError" in scripts["app.js"]
    assert "aria-checked" in scripts["app.js"]
    assert "selectedPanel:" not in scripts["store.js"]
    assert "document.createElement(\"details\")" in scripts["render.js"]
    assert "humanToolLabel" in scripts["render.js"]
    assert "run?.workspace_name" in scripts["project-groups.js"]
    assert '"不可用"' in scripts["render.js"]
    assert "!run.historical && ACTIVE_STATUSES.has(run.status)" in scripts["render.js"]
    assert "app_interrupted" in scripts["render.js"]
    assert 'if (connectionState === "reconnecting")' in scripts["app.js"]
    assert "if (run?.historical)" in scripts["app.js"]
    assert "!run.historical && ACTIVE_RUN_STATUSES.has(run.status)" in scripts["app.js"]
    assert "shortId(run.id)" not in scripts["render.js"]
    assert "activity-timeline" not in scripts["app.js"]
    assert 'elements.taskInput.value = "";\n    resizeComposer();' in scripts["app.js"]
    assert "applyWorkspace(result);\n      await refreshRuns();" in scripts["app.js"]
    assert "execCommand" not in combined


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


def css_rule(css: str, selector: str) -> str:
    start = css.index(f"{selector} {{")
    return css[start : css.index("}", start) + 1]
