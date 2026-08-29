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
from bluewhale_agent.history.conversation import restore_conversation
from bluewhale_agent.history.importer import ImportResult, LegacyHistoryImporter
from bluewhale_agent.history.projector import project_history
from bluewhale_agent.history.repository import HistoryRecord, HistoryRepository
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
from bluewhale_agent.web.schemas import RunContinueRequest, RunCreateRequest, RunResponse
from bluewhale_agent.web.workspaces import WorkspaceResolver, WorkspaceSelectionError

ProviderFactory = Callable[[], ModelProvider]


class RunConflictError(RuntimeError):
    """Raised when a run id or the single-active-run slot is occupied."""


class RunNotFoundError(KeyError):
    """Raised when a requested in-memory run is unknown."""


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
            workspace_name=self.workspace.name or str(self.workspace),
            workspace_available=self.workspace.is_dir(),
            historical=False,
            continuable=result is not None and self.workspace.is_dir(),
            status=result.status if result is not None else self.status,
            stop_reason=result.stop_reason if result is not None else None,
            verified=result.verified if result is not None else None,
            final_answer=result.final_answer if result is not None else None,
            steps_taken=result.steps_taken if result is not None else 0,
            repair_attempts=result.repair_attempts if result is not None else 0,
            created_at=self.created_at,
        )


@dataclass(frozen=True, slots=True)
class HistoricalSession:
    """Read-only session reconstructed from the local history index."""

    record: HistoryRecord
    trajectory: TrajectoryStore

    @property
    def id(self) -> str:
        return self.record.id

    def response(self) -> RunResponse:
        return RunResponse(
            id=self.record.id,
            task=self.record.task,
            workspace=str(self.record.workspace),
            workspace_name=self.record.workspace_name,
            workspace_available=self.record.workspace_available,
            historical=True,
            continuable=self.record.workspace_available,
            status=self.record.status,
            stop_reason=self.record.stop_reason,
            verified=self.record.verified,
            final_answer=self.record.final_answer,
            steps_taken=self.record.steps_taken,
            repair_attempts=self.record.repair_attempts,
            created_at=self.record.created_at,
        )


SessionView = RunSession | HistoricalSession


class SessionManager:
    """Keep historical sessions while allowing at most one active run."""

    def __init__(
        self,
        *,
        workspace_root: Path | None = None,
        workspace_resolver: WorkspaceResolver | None = None,
        provider_factory: ProviderFactory,
        limits: Limits | None = None,
        heartbeat_seconds: float = 15.0,
        approval_broker: ApprovalBroker | None = None,
        history_repository: HistoryRepository | None = None,
    ) -> None:
        if heartbeat_seconds <= 0:
            raise ValueError("heartbeat_seconds must be positive")
        if (workspace_root is None) == (workspace_resolver is None):
            raise ValueError("provide exactly one of workspace_root or workspace_resolver")
        if workspace_resolver is None:
            from bluewhale_agent.web.workspaces import RootWorkspaceResolver

            assert workspace_root is not None
            workspace_resolver = RootWorkspaceResolver(workspace_root)
        self._workspace_resolver = workspace_resolver
        self._provider_factory = provider_factory
        self._limits = limits or Limits()
        self._heartbeat_seconds = heartbeat_seconds
        self.approvals = approval_broker or ApprovalBroker()
        self._history = history_repository
        if self._history is not None:
            self._history.recover_interrupted()
        self._sessions: dict[str, RunSession] = {}
        self._lock = asyncio.Lock()

    async def create(self, request: RunCreateRequest) -> RunSession:
        async with self._lock:
            run_id = request.run_id or uuid4().hex
            if run_id in self._sessions or (
                self._history is not None and self._history.contains(run_id)
            ):
                raise RunConflictError(f"Run already exists: {run_id}")
            if any(self._is_active(session) for session in self._sessions.values()):
                raise RunConflictError("Another run is already active")

            workspace = self._workspace_resolver.resolve(request)
            try:
                provider = self._provider_factory()
            except (ValueError, RuntimeError) as error:
                raise ProviderConfigurationError(str(error)) from error

            trajectory = TrajectoryStore(
                workspace,
                run_id,
                runs_root=self._history.runs_root if self._history is not None else None,
            )
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
            if self._history is not None:
                self._history.add(
                    HistoryRecord(
                        id=run_id,
                        task=request.task,
                        workspace=workspace,
                        workspace_name=workspace.name or str(workspace),
                        status=RunStatus.INITIALIZING,
                        stop_reason=None,
                        verified=None,
                        final_answer=None,
                        steps_taken=0,
                        repair_attempts=0,
                        created_at=session.created_at,
                        updated_at=session.created_at,
                        events_path=trajectory.events_path,
                    )
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
                event_sink=lambda stored: self._record_event(session, stored),
                approval_handler=approval_handler,
                permission_mode=request.permission_mode,
            )
            self._sessions[run_id] = session
            session.background = asyncio.create_task(self._execute(session, loop, request.task))
            return session

    async def continue_run(
        self,
        run_id: str,
        request: RunContinueRequest,
    ) -> RunSession:
        """Append one new user turn to an existing local trajectory."""
        async with self._lock:
            previous = self.get(run_id)
            if isinstance(previous, RunSession) and self._is_active(previous):
                raise RunConflictError("Run is already active")
            if any(
                self._is_active(session)
                for session_id, session in self._sessions.items()
                if session_id != run_id
            ):
                raise RunConflictError("Another run is already active")

            workspace = (
                previous.record.workspace
                if isinstance(previous, HistoricalSession)
                else previous.workspace
            )
            if not workspace.is_dir():
                raise WorkspaceSelectionError("历史任务的工作区当前不可用")
            selection = RunCreateRequest(
                task=request.task,
                workspace=request.workspace,
                workspace_grant_id=request.workspace_grant_id,
                permission_mode=request.permission_mode,
            )
            selected_workspace = self._workspace_resolver.resolve(selection)
            if selected_workspace.resolve(strict=False) != workspace.resolve(strict=False):
                raise WorkspaceSelectionError("当前授权项目与历史任务工作区不一致")

            try:
                provider = self._provider_factory()
            except (ValueError, RuntimeError) as error:
                raise ProviderConfigurationError(str(error)) from error

            trajectory = previous.trajectory
            seed = restore_conversation(trajectory.events_after(0))
            event_bus = EventBus()
            cancel_event = asyncio.Event()
            title = (
                previous.record.task
                if isinstance(previous, HistoricalSession)
                else previous.task
            )
            created_at = (
                previous.record.created_at
                if isinstance(previous, HistoricalSession)
                else previous.created_at
            )
            session = RunSession(
                id=run_id,
                task=title,
                workspace=workspace,
                created_at=created_at,
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
                event_sink=lambda stored: self._record_event(session, stored),
                approval_handler=approval_handler,
                permission_mode=request.permission_mode,
                initial_history=seed.messages,
                initial_observations=seed.observations,
            )
            self._sessions[run_id] = session
            session.background = asyncio.create_task(self._execute(session, loop, request.task))
            return session

    def list(self) -> tuple[SessionView, ...]:
        combined: list[SessionView] = list(self._sessions.values())
        if self._history is not None:
            live_ids = set(self._sessions)
            combined.extend(
                self._historical(record)
                for record in self._history.list()
                if record.id not in live_ids
            )
        return tuple(sorted(combined, key=lambda session: session.response().created_at))

    def has_active_run(self) -> bool:
        return any(self._is_active(session) for session in self._sessions.values())

    def import_workspace_history(self, workspace: Path) -> ImportResult:
        if self._history is None:
            return ImportResult()
        return LegacyHistoryImporter(self._history).import_workspace(workspace)

    def workspace_for_run(self, run_id: str) -> Path | None:
        """Resolve a workspace only from an existing in-memory or indexed run id."""
        live = self._sessions.get(run_id)
        if live is not None:
            return live.workspace
        record = self._history.get(run_id) if self._history is not None else None
        return record.workspace if record is not None else None

    def get(self, run_id: str) -> SessionView:
        try:
            return self._sessions[run_id]
        except KeyError:
            record = self._history.get(run_id) if self._history is not None else None
            if record is None:
                raise RunNotFoundError(run_id) from None
            return self._historical(record)

    async def stop(self, run_id: str) -> RunSession:
        session = self.get(run_id)
        if isinstance(session, HistoricalSession):
            raise RunConflictError("Historical runs are read-only")
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
        if isinstance(session, HistoricalSession):
            for stored in session.trajectory.events_after(after_sequence):
                yield self._format_event(stored)
            return
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
        if isinstance(session, HistoricalSession):
            raise RunConflictError("Historical runs are read-only")
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
        if hasattr(session, "event_bus"):
            session.event_bus.publish(stored)
        return stored

    async def _execute(self, session: RunSession, loop: AgentLoop, task: str) -> None:
        result = await loop.run(task)
        session.result = result
        session.status = result.status

    def _record_event(self, session: RunSession, stored: StoredEvent) -> None:
        session.event_bus.publish(stored)
        if self._history is None:
            return
        events = session.trajectory.events_after(0)
        self._history.update(
            project_history(session.id, session.workspace, session.trajectory.events_path, events)
        )

    def _historical(self, record: HistoryRecord) -> HistoricalSession:
        trajectory = TrajectoryStore(
            record.workspace,
            record.id,
            runs_root=record.events_path.parent.parent,
        )
        return HistoricalSession(record=record, trajectory=trajectory)

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
