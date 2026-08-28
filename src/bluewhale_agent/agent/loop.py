"""Single asynchronous orchestration loop for one BlueWhale agent run."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic

from bluewhale_agent.agent.state import AgentState
from bluewhale_agent.context.manager import ContextBudgetError, ContextManager
from bluewhale_agent.context.workspace_map import WorkspaceMapBuilder
from bluewhale_agent.domain.events import EventKind, RunEvent
from bluewhale_agent.domain.models import (
    Action,
    Limits,
    Message,
    MessageRole,
    ModelResponse,
    Observation,
    ObservationStatus,
    RunStatus,
    StopReason,
)
from bluewhale_agent.evidence.ledger import EvidenceLedger, LedgerReport
from bluewhale_agent.providers.base import (
    ModelProtocolError,
    ModelProvider,
    ProviderRequestError,
)
from bluewhale_agent.runtime.command import RunCommandTool
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.runtime.permissions import (
    PermissionMode,
    PermissionPolicy,
    PermissionResult,
)
from bluewhale_agent.tools.base import ToolContext
from bluewhale_agent.tools.filesystem import ListFilesTool, ReadFileTool, SearchTextTool
from bluewhale_agent.tools.mutation import ApplyPatchTool, GetDiffTool, WriteFileTool
from bluewhale_agent.tools.registry import ToolRegistry
from bluewhale_agent.trajectory.store import StoredEvent, TrajectoryStore
from bluewhale_agent.verification.discovery import (
    VerificationCommand,
    discover_verification_commands,
)
from bluewhale_agent.verification.gate import (
    VerificationGate,
    VerificationOutcome,
    VerificationResult,
)

_SYSTEM_PROMPT = """You are BlueWhale, a local evidence-driven coding agent.
Use the supplied tools to inspect and change only the selected workspace.
Do not claim that a change works without local verification evidence.
When the task is complete, respond with a concise factual summary and no tool calls.
"""


@dataclass(frozen=True)
class AgentRunResult:
    """Deterministic terminal result returned to the API and future GUI."""

    run_id: str
    task: str
    status: RunStatus
    stop_reason: StopReason
    verified: bool | None
    final_answer: str | None
    steps_taken: int
    repair_attempts: int
    actions: tuple[Action, ...]
    observations: tuple[Observation, ...]
    evidence_report: LedgerReport
    verification: VerificationOutcome | None
    trajectory: TrajectoryStore


class _TerminalRun(RuntimeError):
    def __init__(self, reason: StopReason, *, verified: bool | None = None) -> None:
        super().__init__(reason.value)
        self.reason = reason
        self.verified = verified


class AgentLoop:
    """Coordinate model turns and local components without implementing their work."""

    def __init__(
        self,
        *,
        run_id: str,
        workspace: Path,
        provider: ModelProvider,
        limits: Limits | None = None,
        cancel_event: asyncio.Event | None = None,
        clock: Callable[[], float] = monotonic,
        max_context_chars: int = 50_000,
        trajectory: TrajectoryStore | None = None,
        event_sink: Callable[[StoredEvent], None] | None = None,
        approval_handler: Callable[[Action, PermissionResult], Awaitable[bool]] | None = None,
        permission_mode: PermissionMode = PermissionMode.BALANCED,
    ) -> None:
        self._run_id = run_id
        self._provider = provider
        self._limits = limits or Limits()
        self._cancel_event = cancel_event or asyncio.Event()
        self._clock = clock
        self._paths = WorkspacePaths(workspace)
        self._context = ToolContext(
            paths=self._paths,
            command_timeout_seconds=self._limits.command_timeout_seconds,
        )
        self._registry = ToolRegistry(
            tools=[
                ListFilesTool(),
                ReadFileTool(),
                SearchTextTool(),
                WriteFileTool(),
                ApplyPatchTool(),
                GetDiffTool(),
                RunCommandTool(),
            ],
            context=self._context,
            permission_policy=PermissionPolicy(paths=self._paths, mode=permission_mode),
            approval_handler=approval_handler,
        )
        self._context_manager = ContextManager(max_chars=max_context_chars)
        self._workspace_map = WorkspaceMapBuilder(self._paths)
        self._ledger = EvidenceLedger()
        self._gate = VerificationGate(max_repair_attempts=self._limits.max_repair_attempts)
        self._store = trajectory or TrajectoryStore(self._paths.root, run_id)
        if self._store.run_id != run_id:
            raise ValueError("Trajectory store run id must match the agent run id")
        self._event_sink = event_sink
        self._state: AgentState | None = None
        self._task = ""
        self._started_at = 0.0
        self._history: list[Message] = []
        self._actions: list[Action] = []
        self._observations: list[Observation] = []
        self._unresolved_errors: list[str] = []
        self._consecutive_format_errors = 0
        self._final_answer: str | None = None
        self._verification: VerificationOutcome | None = None
        self._verification_action = 0

    async def run(self, task: str) -> AgentRunResult:
        """Execute until a deterministic terminal condition is reached."""

        self._task = task
        self._state = AgentState.start(task, self._limits)
        self._started_at = self._clock()
        self._emit(EventKind.RUN_STARTED, {"task": task})
        self._state.mark_running()
        self._emit_state()

        try:
            while True:
                response = await self._request_model()
                self._record_response(response)
                if response.tool_calls:
                    await self._execute_actions(response.tool_calls)
                    continue

                if not self._context.changeset.changes:
                    return self._finish(StopReason.COMPLETED, verified=None)
                return await self._verify_changes()
        except _TerminalRun as terminal:
            return self._finish(terminal.reason, verified=terminal.verified)
        except asyncio.CancelledError:
            return self._finish(StopReason.USER_STOPPED, verified=None)
        except Exception as error:
            self._unresolved_errors.append(
                f"Unexpected component error: {type(error).__name__}: {error}"
            )
            return self._finish(StopReason.TOOL_ERROR, verified=None)

    async def _request_model(self) -> ModelResponse:
        while True:
            self._guard_model_call()
            try:
                response = await self._provider.complete(
                    self._build_messages(), self._registry.schemas()
                )
            except ModelProtocolError as error:
                self._state_required().record_model_call()
                self._consecutive_format_errors += 1
                self._unresolved_errors.append(f"Model protocol error: {error}")
                if self._consecutive_format_errors >= self._limits.max_consecutive_format_errors:
                    raise _TerminalRun(StopReason.MODEL_PROTOCOL_ERROR) from error
                continue
            except ProviderRequestError as error:
                self._state_required().record_model_call()
                self._unresolved_errors.append(str(error))
                raise _TerminalRun(StopReason.API_ERROR) from error
            except ContextBudgetError as error:
                raise _TerminalRun(StopReason.TOOL_ERROR) from error

            self._state_required().record_model_call()
            self._consecutive_format_errors = 0
            return response

    def _build_messages(self) -> list[Message]:
        working_set = {change.path: change.after for change in self._context.changeset.changes}
        return self._context_manager.build(
            system_prompt=_SYSTEM_PROMPT,
            task=self._task,
            status=self._state_required().status,
            unresolved_errors=self._unresolved_errors,
            working_set=working_set,
            workspace_map=self._workspace_map.build(),
            history=self._history,
            observations=self._observations,
        )

    def _record_response(self, response: ModelResponse) -> None:
        message = Message(
            role=MessageRole.ASSISTANT,
            content=response.content,
            reasoning_content=response.reasoning_content,
            tool_calls=response.tool_calls,
        )
        self._history.append(message)
        if response.content:
            self._final_answer = response.content
            self._ledger.record_model_statement(response.content)
        self._emit(
            EventKind.MODEL_RESPONSE,
            {
                "content": response.content,
                "finish_reason": response.finish_reason,
                "tool_calls": [item.model_dump(mode="json") for item in response.tool_calls],
            },
        )

    async def _execute_actions(
        self,
        actions: Sequence[Action],
        *,
        verification: bool = False,
    ) -> None:
        for action in actions:
            self._guard_runtime()
            self._actions.append(action)
            self._emit(
                EventKind.ACTION_REQUESTED,
                {"action": action.model_dump(mode="json"), "verification": verification},
            )
            observation = await self._registry.dispatch(action)
            self._observations.append(observation)
            stored = self._emit(
                EventKind.OBSERVATION_RECEIVED,
                {
                    "observation": observation.model_dump(mode="json"),
                    "verification": verification,
                },
            )
            self._ledger.record(
                action,
                observation,
                source_event_id=stored.event.id,
                verification=verification,
            )
            if not verification:
                self._history.append(
                    Message(
                        role=MessageRole.TOOL,
                        content=observation.model_dump_json(),
                        tool_call_id=action.id,
                    )
                )
            if observation.status is ObservationStatus.DENIED:
                raise _TerminalRun(StopReason.PERMISSION_DENIED)
            if observation.status is not ObservationStatus.SUCCESS:
                self._unresolved_errors.append(observation.summary)

    async def _verify_changes(self) -> AgentRunResult:
        state = self._state_required()
        state.begin_verification()
        self._emit_state()
        commands = discover_verification_commands(self._paths)

        async def runner(command: VerificationCommand) -> Observation:
            self._verification_action += 1
            action = Action(
                id=f"verification-{self._verification_action}",
                tool_name="run_command",
                arguments={"command": command.command},
            )
            await self._execute_actions((action,), verification=True)
            return self._observations[-1]

        async def repair(results: tuple[VerificationResult, ...], attempt: int) -> None:
            state.repair_attempts = attempt
            self._unresolved_errors = [
                f"Verification failed: {result.summary}\n{result.content}" for result in results
            ]
            response = await self._request_model()
            self._record_response(response)
            if response.tool_calls:
                await self._execute_actions(response.tool_calls)

        self._verification = await self._gate.run(commands, runner, repair)
        state.repair_attempts = self._verification.repair_attempts
        self._emit(
            EventKind.VERIFICATION_FINISHED,
            {"outcome": self._verification.model_dump(mode="json")},
        )
        return self._finish(
            self._verification.stop_reason,
            verified=self._verification.passed,
        )

    def _guard_model_call(self) -> None:
        self._guard_runtime()
        if self._state_required().steps_taken >= self._limits.max_steps:
            raise _TerminalRun(StopReason.STEP_LIMIT)

    def _guard_runtime(self) -> None:
        if self._cancel_event.is_set():
            raise _TerminalRun(StopReason.USER_STOPPED)
        if self._clock() - self._started_at >= self._limits.max_wall_time_seconds:
            raise _TerminalRun(StopReason.TIME_LIMIT)

    def _finish(self, reason: StopReason, *, verified: bool | None) -> AgentRunResult:
        state = self._state_required()
        if state.can_continue:
            state.finish(reason, verified=verified)
        self._emit_state()
        self._emit(
            EventKind.RUN_FINISHED,
            {
                "status": state.status.value,
                "stop_reason": reason.value,
                "verified": verified,
                "final_answer": self._final_answer,
            },
        )
        return AgentRunResult(
            run_id=self._run_id,
            task=self._task,
            status=state.status,
            stop_reason=reason,
            verified=verified,
            final_answer=self._final_answer,
            steps_taken=state.steps_taken,
            repair_attempts=state.repair_attempts,
            actions=tuple(self._actions),
            observations=tuple(self._observations),
            evidence_report=self._ledger.report(),
            verification=self._verification,
            trajectory=self._store,
        )

    def _emit_state(self) -> StoredEvent:
        state = self._state_required()
        return self._emit(
            EventKind.STATE_CHANGED,
            {
                "status": state.status.value,
                "steps_taken": state.steps_taken,
                "repair_attempts": state.repair_attempts,
            },
        )

    def _emit(self, kind: EventKind, payload: dict[str, object]) -> StoredEvent:
        stored = self._store.append(RunEvent(run_id=self._run_id, kind=kind, payload=payload))
        if self._event_sink is not None:
            self._event_sink(stored)
        return stored

    def _state_required(self) -> AgentState:
        if self._state is None:
            raise RuntimeError("Agent run has not started")
        return self._state
