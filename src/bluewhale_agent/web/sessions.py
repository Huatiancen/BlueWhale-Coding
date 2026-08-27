"""Lifecycle ownership for background agent runs."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator, Callable
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from bluewhale_agent.agent.loop import AgentLoop, AgentRunResult
from bluewhale_agent.domain.events import EventKind, RunEvent
from bluewhale_agent.domain.models import Action, Limits, RunStatus
from bluewhale_agent.providers.base import ModelProvider
from bluewhale_agent.runtime.permissions import PermissionResult
from bluewhale_agent.trajectory.store import StoredEvent, TrajectoryStore
from bluewhale_agent.web.approvals import (
    ApprovalBroker,
    ApprovalDecision,
    ApprovalRecord,
    ApprovalStatus,
)
from bluewhale_agent.web.event_bus import EventBus
from bluewhale_agent.web.schemas import RunCreateRequest, RunResponse

ProviderFactory = Callable[[], ModelProvider]


class RunConflictError(RuntimeError):
    """Raised when a run id or the single-active-run slot is occupied."""


class RunNotFoundError(KeyError):
    """Raised when a requested in-memory run is unknown."""


class WorkspaceSelectionError(ValueError):
    """Raised when an API-selected workspace violates the configured boundary."""


class ProviderConfigurationError(RuntimeError):
    """Raised when the configured model provider cannot be constructed."""


@dataclass
class RunSession:
    id: str
    task: str
    workspace: Path
    created_at: datetime
    cancel_event: asyncio.Event
    trajectory: TrajectoryStore
    event_bus: EventBus
    status: RunStatus = RunStatus.INITIALIZING
    background: asyncio.Task[None] | None = None
    result: AgentRunResult | None = None

    def response(self) -> RunResponse:
        result = self.result
        return RunResponse(
            id=self.id,
            task=self.task,
            workspace=str(self.workspace),
            status=result.status if result is not None else self.status,
            stop_reason=result.stop_reason if result is not None else None,
            verified=result.verified if result is not None else None,
            final_answer=result.final_answer if result is not None else None,
            steps_taken=result.steps_taken if result is not None else 0,
            repair_attempts=result.repair_attempts if result is not None else 0,
            created_at=self.created_at,
        )


class SessionManager:
    """Keep historical sessions while allowing at most one active run."""

    def __init__(
        self,
        *,
        workspace_root: Path,
        provider_factory: ProviderFactory,
        limits: Limits | None = None,
        heartbeat_seconds: float = 15.0,
        approval_broker: ApprovalBroker | None = None,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        self._workspace_root = workspace_root.resolve(strict=True)
        if not self._workspace_root.is_dir():
            raise ValueError("workspace_root must be a directory")
        self._provider_factory = provider_factory
        self._limits = limits or Limits()
        self._heartbeat_seconds = heartbeat_seconds
        self.approvals = approval_broker or ApprovalBroker()
        self._sessions: dict[str, RunSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, request: RunCreateRequest) -> RunSession:
        async with self._lock:
            run_id = request.run_id or uuid4().hex
            if run_id in self._sessions:
                raise RunConflictError(f"Run already exists: {run_id}")
            if any(self._is_active(session) for session in self._sessions.values()):
                raise RunConflictError("Another run is already active")

            workspace = self._resolve_workspace(request.workspace)
            try:
                provider = self._provider_factory()
            except (ValueError, RuntimeError) as error:
                raise ProviderConfigurationError(str(error)) from error

            trajectory = TrajectoryStore(workspace, run_id)
            event_bus = EventBus()
            cancel_event = asyncio.Event()
            session = RunSession(
                id=run_id,
                task=request.task,
                workspace=workspace,
                created_at=datetime.now(UTC),
                cancel_event=cancel_event,
                trajectory=trajectory,
                event_bus=event_bus,
                status=RunStatus.RUNNING,
            )

            async def approval_handler(action: Action, permission: PermissionResult) -> bool:
                return await self._request_approval(session, action, permission)

            loop = AgentLoop(
                run_id=run_id,
                workspace=workspace,
                provider=provider,
                limits=self._limits,
                cancel_event=cancel_event,
                trajectory=trajectory,
                event_sink=event_bus.publish,
                approval_handler=approval_handler,
            )
            self._sessions[run_id] = session
            session.background = asyncio.create_task(self._execute(session, loop))
            return session

    def list(self) -> tuple[RunSession, ...]:
        return tuple(self._sessions.values())

    def get(self, run_id: str) -> RunSession:
        try:
            return self._sessions[run_id]
        except KeyError as error:
            raise RunNotFoundError(run_id) from error

    async def stop(self, run_id: str) -> RunSession:
        session = self.get(run_id)
        background = session.background
        if background is None or background.done():
            return session
        pending = self.approvals.pending_for_run(run_id)
        self.approvals.cancel_run(run_id)
        for approval in pending:
            cancelled = self.approvals.get(run_id, approval.id)
            self._publish_approval(session, EventKind.APPROVAL_RESOLVED, cancelled)
        session.cancel_event.set()
        background.cancel()
        with suppress(asyncio.CancelledError):
            await background
        return session

    async def stream_events(
        self,
        run_id: str,
        after_sequence: int,
    ) -> AsyncIterator[str]:
        session = self.get(run_id)
        cursor = after_sequence
        async with session.event_bus.subscribe() as queue:
            for stored in session.trajectory.events_after(cursor):
                cursor = stored.sequence
                yield self._format_event(stored)

            while True:
                background = session.background
                if background is not None and background.done() and queue.empty():
                    break
                try:
                    stored = await asyncio.wait_for(queue.get(), timeout=self._heartbeat_seconds)
                except TimeoutError:
                    if background is not None and background.done():
                        break
                    yield ": heartbeat\n\n"
                    continue
                if stored.sequence <= cursor:
                    continue
                cursor = stored.sequence
                yield self._format_event(stored)

    async def shutdown(self) -> None:
        active = [
            session
            for session in self._sessions.values()
            if session.background is not None and not session.background.done()
        ]
        for session in active:
            self.approvals.cancel_run(session.id)
            session.cancel_event.set()
        backgrounds = [session.background for session in active if session.background is not None]
        for background in backgrounds:
            background.cancel()
        if backgrounds:
            await asyncio.gather(*backgrounds, return_exceptions=True)

    def resolve_approval(
        self,
        run_id: str,
        approval_id: str,
        decision: ApprovalDecision,
    ) -> ApprovalRecord:
        session = self.get(run_id)
        approval = self.approvals.resolve(run_id, approval_id, decision)
        self._publish_approval(session, EventKind.APPROVAL_RESOLVED, approval)
        return approval

    async def _request_approval(
        self,
        session: RunSession,
        action: Action,
        permission: PermissionResult,
    ) -> bool:
        previous_status = session.status
        session.status = RunStatus.WAITING_APPROVAL
        self._publish(
            session,
            EventKind.STATE_CHANGED,
            {"status": RunStatus.WAITING_APPROVAL.value},
        )
        approval_id: str | None = None

        def publish_pending(approval: ApprovalRecord) -> None:
            nonlocal approval_id
            approval_id = approval.id
            self._publish_approval(session, EventKind.APPROVAL_REQUESTED, approval)

        try:
            approved = await self.approvals.request(
                session.id,
                action,
                permission.reason,
                on_pending=publish_pending,
            )
            if approval_id is not None:
                approval = self.approvals.get(session.id, approval_id)
                if approval.status is ApprovalStatus.EXPIRED:
                    self._publish_approval(session, EventKind.APPROVAL_RESOLVED, approval)
            return approved
        finally:
            if session.status is RunStatus.WAITING_APPROVAL:
                session.status = previous_status
                self._publish(
                    session,
                    EventKind.STATE_CHANGED,
                    {"status": previous_status.value},
                )

    @staticmethod
    def _publish_approval(
        session: RunSession,
        kind: EventKind,
        approval: ApprovalRecord,
    ) -> StoredEvent:
        return SessionManager._publish(
            session,
            kind,
            {"approval": approval.model_dump(mode="json")},
        )

    @staticmethod
    def _publish(
        session: RunSession,
        kind: EventKind,
        payload: dict[str, object],
    ) -> StoredEvent:
        stored = session.trajectory.append(RunEvent(run_id=session.id, kind=kind, payload=payload))
        session.event_bus.publish(stored)
        return stored

    async def _execute(self, session: RunSession, loop: AgentLoop) -> None:
        result = await loop.run(session.task)
        session.result = result
        session.status = result.status

    def _resolve_workspace(self, requested: str) -> Path:
        relative = Path(requested)
        candidate = (
            relative.resolve(strict=False)
            if relative.is_absolute()
            else (self._workspace_root / relative).resolve(strict=False)
        )
        try:
            selected_relative = candidate.relative_to(self._workspace_root)
        except ValueError as error:
            raise WorkspaceSelectionError(
                "Workspace must stay inside the configured root"
            ) from error
        if any(
            part in {".bluewhale", ".git"} or part == ".env" or part.startswith(".env.")
            for part in selected_relative.parts
        ):
            raise WorkspaceSelectionError("Workspace is protected")
        if not candidate.is_dir():
            raise WorkspaceSelectionError("Workspace does not exist or is not a directory")
        return candidate

    @staticmethod
    def _is_active(session: RunSession) -> bool:
        return session.background is not None and not session.background.done()

    @staticmethod
    def _format_event(event: StoredEvent) -> str:
        return (
            f"id: {event.sequence}\n"
            f"event: {event.event.kind.value}\n"
            f"data: {event.model_dump_json()}\n\n"
        )
