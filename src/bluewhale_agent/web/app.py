"""FastAPI application factory for local BlueWhale sessions."""

from __future__ import annotations

import mimetypes
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, Query, Request, status
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import RequestResponseEndpoint
from starlette.responses import Response

from bluewhale_agent.config import Settings
from bluewhale_agent.history.conversation import ConversationHistoryError
from bluewhale_agent.history.repository import HistoryRepository
from bluewhale_agent.providers.base import ModelProvider
from bluewhale_agent.providers.deepseek import DeepSeekProvider
from bluewhale_agent.runtime.paths import (
    PathAccessDeniedError,
    PathAccessError,
    WorkspacePaths,
)
from bluewhale_agent.trajectory.store import TrajectoryCorruptionError
from bluewhale_agent.web.approvals import (
    ApprovalBroker,
    ApprovalConflictError,
    ApprovalNotFoundError,
    ApprovalRecord,
)
from bluewhale_agent.web.desktop_auth import DESKTOP_COOKIE, DesktopSessionGuard
from bluewhale_agent.web.schemas import (
    ApprovalResolveRequest,
    HealthResponse,
    RunContinueRequest,
    RunCreateRequest,
    RunResponse,
    WorkspaceFileResponse,
)
from bluewhale_agent.web.sessions import (
    ProviderConfigurationError,
    ProviderFactory,
    RunConflictError,
    RunNotFoundError,
    SessionManager,
    SessionView,
)
from bluewhale_agent.web.workspaces import (
    RootWorkspaceResolver,
    WorkspaceResolver,
    WorkspaceSelectionError,
)


def create_app(
    *,
    workspace: Path | None = None,
    workspace_resolver: WorkspaceResolver | None = None,
    provider_factory: ProviderFactory | None = None,
    settings: Settings | None = None,
    approval_timeout_seconds: float | None = None,
    desktop_token: str | None = None,
    history_root: Path | None = None,
) -> FastAPI:
    """Build an app whose agent runs are restricted to one configured root."""

    if (workspace is None) == (workspace_resolver is None):
        raise ValueError("provide exactly one of workspace or workspace_resolver")
    selected_settings = settings or Settings(workspace=workspace or Path.cwd())

    def default_provider_factory() -> ModelProvider:
        return DeepSeekProvider(selected_settings)

    selected_resolver = workspace_resolver
    if selected_resolver is None:
        assert workspace is not None
        selected_resolver = RootWorkspaceResolver(workspace)

    approvals = ApprovalBroker(timeout_seconds=approval_timeout_seconds)
    manager = SessionManager(
        workspace_resolver=selected_resolver,
        provider_factory=provider_factory or default_provider_factory,
        limits=selected_settings.limits,
        approval_broker=approvals,
        history_repository=HistoryRepository(history_root) if history_root is not None else None,
    )

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        yield
        await manager.shutdown()

    app = FastAPI(title="BlueWhale Coding Agent", lifespan=lifespan)
    app.state.sessions = manager
    app.state.approvals = approvals
    desktop_guard = DesktopSessionGuard(desktop_token) if desktop_token is not None else None

    @app.middleware("http")
    async def prevent_local_ui_cache(
        request: Request,
        call_next: RequestResponseEndpoint,
    ) -> Response:
        response = await call_next(request)
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Cache-Control"] = "no-store"
        return response

    if desktop_guard is not None:

        @app.middleware("http")
        async def require_desktop_session(
            request: Request,
            call_next: RequestResponseEndpoint,
        ) -> Response:
            if request.url.path in {"/api/health", "/desktop/bootstrap"}:
                return await call_next(request)
            if not desktop_guard.accepts_session(request.cookies.get(DESKTOP_COOKIE)):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Desktop session required"},
                )
            return await call_next(request)

    static_directory = Path(__file__).parent / "static"
    app.mount("/static", StaticFiles(directory=static_directory), name="static")

    @app.get("/", include_in_schema=False)
    async def index() -> FileResponse:
        return FileResponse(static_directory / "index.html")

    @app.get("/api/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse()

    if desktop_guard is not None:

        @app.get("/desktop/bootstrap", include_in_schema=False)
        async def desktop_bootstrap(token: str | None = None) -> Response:
            if not desktop_guard.accepts_bootstrap(token):
                return JSONResponse(
                    status_code=401,
                    content={"detail": "Invalid desktop bootstrap token"},
                )
            response = RedirectResponse(
                url=f"/?v={desktop_guard.cache_token}",
                status_code=303,
            )
            response.set_cookie(
                DESKTOP_COOKIE,
                desktop_guard.session_token,
                httponly=True,
                samesite="strict",
                path="/",
            )
            return response

    @app.post(
        "/api/runs",
        response_model=RunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def create_run(request: RunCreateRequest) -> RunResponse:
        try:
            session = await manager.create(request)
        except RunConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except WorkspaceSelectionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ProviderConfigurationError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return session.response()

    @app.get("/api/runs", response_model=list[RunResponse])
    async def list_runs() -> list[RunResponse]:
        return [session.response() for session in manager.list()]

    @app.post(
        "/api/runs/{run_id}/continue",
        response_model=RunResponse,
        status_code=status.HTTP_202_ACCEPTED,
    )
    async def continue_run(run_id: str, request: RunContinueRequest) -> RunResponse:
        try:
            session = await manager.continue_run(run_id, request)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}") from error
        except (
            RunConflictError,
            ConversationHistoryError,
            TrajectoryCorruptionError,
        ) as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        except WorkspaceSelectionError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        except ProviderConfigurationError as error:
            raise HTTPException(status_code=503, detail=str(error)) from error
        return session.response()

    @app.get("/api/runs/{run_id}", response_model=RunResponse)
    async def get_run(run_id: str) -> RunResponse:
        return _get_session(manager, run_id).response()

    @app.get("/api/runs/{run_id}/files", response_model=WorkspaceFileResponse)
    async def get_run_file(
        run_id: str,
        path: str = Query(min_length=1),
    ) -> WorkspaceFileResponse:
        _get_session(manager, run_id)
        workspace = manager.workspace_for_run(run_id)
        if workspace is None:
            raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}")
        try:
            resolved = WorkspacePaths(workspace).resolve(path)
        except PathAccessDeniedError as error:
            raise HTTPException(status_code=403, detail=str(error)) from error
        except PathAccessError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        if not resolved.is_file() or resolved.is_symlink():
            raise HTTPException(status_code=400, detail="Path must be a regular file")
        raw = resolved.read_bytes()
        if len(raw) > 1_000_000:
            raise HTTPException(status_code=413, detail="File is too large to preview")
        if b"\x00" in raw:
            raise HTTPException(status_code=415, detail="Binary files cannot be shown as text")
        try:
            content = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise HTTPException(status_code=415, detail="File is not UTF-8 text") from error
        mime_type = mimetypes.guess_type(resolved.name)[0] or "text/plain"
        return WorkspaceFileResponse(
            path=resolved.relative_to(workspace.resolve()).as_posix(),
            content=content,
            mime_type=mime_type,
            size=len(raw),
        )

    @app.post("/api/runs/{run_id}/stop", response_model=RunResponse)
    async def stop_run(run_id: str) -> RunResponse:
        try:
            session = await manager.stop(run_id)
        except RunNotFoundError as error:
            raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}") from error
        except RunConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error
        return session.response()

    @app.post(
        "/api/runs/{run_id}/approvals/{approval_id}",
        response_model=ApprovalRecord,
    )
    async def resolve_approval(
        run_id: str,
        approval_id: str,
        request: ApprovalResolveRequest,
    ) -> ApprovalRecord:
        try:
            return manager.resolve_approval(run_id, approval_id, request.decision)
        except (RunNotFoundError, ApprovalNotFoundError) as error:
            raise HTTPException(
                status_code=404,
                detail=f"Unknown approval: {approval_id}",
            ) from error
        except ApprovalConflictError as error:
            raise HTTPException(status_code=409, detail=str(error)) from error

    @app.get("/api/runs/{run_id}/events")
    async def events(
        request: Request,
        run_id: str,
        last_event_id: str | None = Header(default=None, alias="Last-Event-ID"),
    ) -> StreamingResponse:
        _get_session(manager, run_id)
        cursor = _parse_cursor(last_event_id)

        async def body() -> AsyncIterator[str]:
            async for item in manager.stream_events(run_id, cursor):
                if await request.is_disconnected():
                    break
                yield item

        return StreamingResponse(
            body(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    return app


def _get_session(manager: SessionManager, run_id: str) -> SessionView:
    try:
        return manager.get(run_id)
    except RunNotFoundError as error:
        raise HTTPException(status_code=404, detail=f"Unknown run: {run_id}") from error


def _parse_cursor(raw: str | None) -> int:
    if raw is None:
        return 0
    try:
        cursor = int(raw)
    except ValueError as error:
        raise HTTPException(
            status_code=400,
            detail="Last-Event-ID must be a non-negative integer",
        ) from error
    if cursor < 0:
        raise HTTPException(
            status_code=400,
            detail="Last-Event-ID must be a non-negative integer",
        )
    return cursor
