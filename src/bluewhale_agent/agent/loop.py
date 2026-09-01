"""Single asynchronous orchestration loop for one BlueWhale agent run."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass
from pathlib import Path
from time import monotonic
from typing import cast

from bluewhale_agent.agent.checkpoints import (
    CheckpointPhase,
    RunCheckpoint,
    RunCheckpointStore,
)
from bluewhale_agent.agent.state import AgentState
from bluewhale_agent.agent.steering import RuntimeInstruction, RuntimeInstructionQueue
from bluewhale_agent.context.instructions import InstructionResolver, ProjectInstructionsError
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
from bluewhale_agent.evidence.ledger import EvidenceLedger, LedgerReport, StepStatus
from bluewhale_agent.providers.base import (
    ModelDelta,
    ModelProtocolError,
    ModelProvider,
    ProviderRequestError,
    StreamInterruptedError,
)
from bluewhale_agent.providers.recovery import repair_tool_history
from bluewhale_agent.runtime.command import RunCommandTool
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.runtime.permissions import (
    PermissionMode,
    PermissionPolicy,
    PermissionResult,
)
from bluewhale_agent.skills.catalog import SkillCatalog, SkillCatalogError
from bluewhale_agent.skills.invocation import SkillInvocationError, parse_skill_invocation
from bluewhale_agent.skills.models import MAX_ACTIVE_SKILLS
from bluewhale_agent.tools.base import ToolContext
from bluewhale_agent.tools.filesystem import ListFilesTool, ReadFileTool, SearchTextTool
from bluewhale_agent.tools.mutation import ApplyPatchTool, GetDiffTool, WriteFileTool
from bluewhale_agent.tools.planning import UpdatePlanTool
from bluewhale_agent.tools.registry import ToolRegistry
from bluewhale_agent.tools.skills import LoadSkillTool, render_loaded_skill
from bluewhale_agent.trajectory.store import StoredEvent, TrajectoryStore
from bluewhale_agent.verification.discovery import (
    VerificationCommand,
    discover_verification_commands,
)
from bluewhale_agent.verification.gate import (
    VerificationGate,
    VerificationLevel,
    VerificationOutcome,
    VerificationResult,
    assess_change_scope,
)

_SYSTEM_PROMPT = """You are BlueWhale, a local evidence-driven coding agent.
Use the supplied tools to inspect and change only the selected workspace.
For non-trivial tasks, call update_plan first and keep its active step current.
Do not claim that a change works without local verification evidence.
Use load_skill when an available Skill description matches the task, before following it.
When the task is complete, respond with a concise factual summary and no tool calls.
"""

_PROGRESS_CHECK_PROMPT = """# Progress checkpoint
This is a non-blocking progress audit after {steps} model calls.
Review completed work, unresolved errors, and remaining goals before acting.
Do not repeat an unsuccessful read, command, or edit path without new evidence.
If the requested changes and verification are complete, call no more tools and give the
final answer. Otherwise choose the single next action with the highest information gain.
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
        initial_history: Sequence[Message] = (),
        initial_observations: Sequence[Observation] = (),
        instruction_queue: RuntimeInstructionQueue | None = None,
        allowed_change_paths: Sequence[str] | None = None,
        resume_checkpoint: RunCheckpoint | None = None,
        skill_user_home: Path | None = None,
    ) -> None:
        self._run_id = run_id
        self._provider = provider
        self._limits = limits or Limits()
        self._cancel_event = cancel_event or asyncio.Event()
        self._clock = clock
        self._paths = WorkspacePaths(workspace)
        self._ledger = EvidenceLedger()
        self._active_step_id: str | None = None
        self._context = ToolContext(
            paths=self._paths,
            command_timeout_seconds=self._limits.command_timeout_seconds,
            command_network_allowed=permission_mode is PermissionMode.FULL,
        )
        self._skill_catalog = SkillCatalog.discover(
            workspace=self._paths.root,
            user_home=skill_user_home,
        )
        self._active_skills: dict[str, str] = {}
        self._registry = ToolRegistry(
            tools=[
                ListFilesTool(),
                ReadFileTool(),
                SearchTextTool(),
                WriteFileTool(),
                ApplyPatchTool(),
                GetDiffTool(),
                LoadSkillTool(self._skill_catalog),
                RunCommandTool(),
                UpdatePlanTool(self._ledger),
            ],
            context=self._context,
            permission_policy=PermissionPolicy(paths=self._paths, mode=permission_mode),
            approval_handler=approval_handler,
        )
        self._context_manager = ContextManager(max_chars=max_context_chars)
        self._workspace_map = WorkspaceMapBuilder(self._paths)
        self._instruction_resolver = InstructionResolver(self._paths.root)
        root_instructions = self._instruction_resolver.resolve_for(".")
        self._project_instructions = root_instructions.render()
        self._instruction_sources = tuple(
            document.source for document in root_instructions.documents
        )
        self._gate = VerificationGate(max_repair_attempts=self._limits.max_repair_attempts)
        self._store = trajectory or TrajectoryStore(self._paths.root, run_id)
        if self._store.run_id != run_id:
            raise ValueError("Trajectory store run id must match the agent run id")
        self._checkpoint_store = RunCheckpointStore(
            self._paths.root,
            run_id,
            runs_root=self._store.run_dir.parent,
        )
        self._event_sink = event_sink
        self._state: AgentState | None = None
        self._task = ""
        self._model_task = ""
        self._started_at = 0.0
        self._prior_history = list(initial_history)
        self._history: list[Message] = []
        self._actions: list[Action] = []
        self._observations = list(initial_observations)
        self._unresolved_errors: list[str] = []
        self._consecutive_format_errors = 0
        self._final_answer: str | None = None
        self._verification: VerificationOutcome | None = None
        self._verification_action = 0
        self._completed_action_ids: list[str] = []
        self._instruction_queue = instruction_queue or RuntimeInstructionQueue()
        self._allowed_change_paths = (
            tuple(allowed_change_paths) if allowed_change_paths is not None else None
        )
        self._resume_checkpoint = resume_checkpoint
        self._stream_recovery_attempts = 0
        self._last_progress_check_step = 0

    async def run(self, task: str) -> AgentRunResult:
        """Execute until a deterministic terminal condition is reached."""

        self._task = task
        self._model_task = task
        self._state = AgentState.start(task, self._limits)
        self._started_at = self._clock()
        resumed = self._restore_checkpoint()
        self._emit(EventKind.RUN_STARTED, {"task": task, "resumed": resumed})
        self._checkpoint(CheckpointPhase.PREPARING)
        self._state.mark_running()
        self._emit_state()

        try:
            self._prepare_explicit_skill(task)
            while True:
                response = await self._request_model()
                if response.tool_calls:
                    self._record_response(response)
                    await self._execute_actions(response.tool_calls)
                    self._deliver_pending_instructions()
                    continue

                pending = self._instruction_queue.drain()
                self._record_response(response, intermediate=bool(pending))
                if pending:
                    self._deliver_instructions(pending)
                    continue

                if not self._context.changeset.changes:
                    return self._finish(StopReason.COMPLETED, verified=None)
                return await self._verify_changes()
        except _TerminalRun as terminal:
            if terminal.reason is StopReason.STEP_LIMIT:
                await self._request_terminal_summary()
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
            self._checkpoint(CheckpointPhase.MODEL_REQUEST)
            try:
                messages = self._build_messages()
                progress_check = self._progress_check_message()
                if progress_check is not None:
                    messages.append(progress_check)
                tools = self._registry.schemas()
                stream = getattr(self._provider, "stream", None)
                if callable(stream):
                    response = cast(
                        ModelResponse,
                        await stream(messages, tools, self._record_delta),
                    )
                else:
                    response = await self._provider.complete(messages, tools)
            except StreamInterruptedError as error:
                partial = error.partial_response
                if partial.content or partial.reasoning_content or partial.tool_calls:
                    self._record_response(partial, intermediate=True)
                self._checkpoint(CheckpointPhase.INTERRUPTED)
                self._state_required().record_model_call()
                self._unresolved_errors.append(str(error))
                if self._stream_recovery_attempts >= self._limits.max_api_retries:
                    raise _TerminalRun(StopReason.API_ERROR) from error
                self._stream_recovery_attempts += 1
                self._history = repair_tool_history(self._history)
                continue
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
            self._stream_recovery_attempts = 0
            return response

    def _restore_checkpoint(self) -> bool:
        checkpoint = self._resume_checkpoint
        if checkpoint is None:
            return False
        if checkpoint.run_id != self._run_id:
            raise ValueError("Resume checkpoint run id must match the agent run id")
        if checkpoint.phase in {CheckpointPhase.COMPLETED, CheckpointPhase.FAILED}:
            return False
        restored = (
            list(checkpoint.messages)
            if checkpoint.task is not None
            else list(self._prior_history)
        )
        if checkpoint.task:
            restored.insert(0, Message(role=MessageRole.USER, content=checkpoint.task))
        self._prior_history = repair_tool_history(restored)
        self._history = []
        self._completed_action_ids = list(checkpoint.completed_action_ids)
        for name in checkpoint.active_skill_names:
            if len(self._active_skills) >= MAX_ACTIVE_SKILLS:
                self._unresolved_errors.append(
                    f"Only {MAX_ACTIVE_SKILLS} active Skills can be restored; "
                    "additional checkpoint Skills were skipped."
                )
                break
            try:
                loaded = self._skill_catalog.load(name, allow_hidden=True)
            except SkillCatalogError:
                self._unresolved_errors.append(
                    f"Previously active Skill {name} is no longer available; it was not restored."
                )
                continue
            self._active_skills[name] = render_loaded_skill(loaded)
        if checkpoint.needs_reconciliation:
            pending = checkpoint.pending_action
            assert pending is not None
            self._unresolved_errors.append(
                f"Interrupted action {pending.id} ({pending.tool_name}) was not replayed; "
                "inspect workspace state before deciding whether to reissue it."
            )
        return True

    def _record_delta(self, delta: ModelDelta) -> None:
        self._emit(EventKind.MODEL_DELTA, delta.model_dump(mode="json"))

    def _build_messages(self) -> list[Message]:
        working_set = {change.path: change.after for change in self._context.changeset.changes}
        return self._context_manager.build(
            system_prompt=_SYSTEM_PROMPT,
            task=self._model_task,
            status=self._state_required().status,
            unresolved_errors=self._unresolved_errors,
            working_set=working_set,
            workspace_map=self._workspace_map.build(),
            history=self._history,
            observations=self._observations,
            prior_history=self._prior_history,
            project_instructions=self._project_instructions,
            available_skills=self._skill_catalog.render_for_model(),
            active_skills=self._active_skills,
        )

    def _progress_check_message(self) -> Message | None:
        """Build one audit instruction at each configured model-call interval."""
        steps = self._state_required().steps_taken
        interval = self._limits.progress_check_interval
        if (
            steps <= 0
            or steps % interval != 0
            or steps <= self._last_progress_check_step
        ):
            return None
        self._last_progress_check_step = steps
        self._emit(
            EventKind.PROGRESS_CHECKED,
            {"model_calls": steps, "interval": interval},
        )
        return Message(
            role=MessageRole.SYSTEM,
            content=_PROGRESS_CHECK_PROMPT.format(steps=steps),
        )

    def _record_response(self, response: ModelResponse, *, intermediate: bool = False) -> None:
        message = Message(
            role=MessageRole.ASSISTANT,
            content=response.content,
            reasoning_content=response.reasoning_content,
            tool_calls=response.tool_calls,
        )
        self._history.append(message)
        if response.content:
            if not response.tool_calls and response.finish_reason != "tool_calls":
                self._final_answer = response.content
            self._ledger.record_model_statement(response.content)
        self._emit(
            EventKind.MODEL_RESPONSE,
            {
                "content": response.content,
                "reasoning_content": response.reasoning_content,
                "finish_reason": response.finish_reason,
                "tool_calls": [item.model_dump(mode="json") for item in response.tool_calls],
                "intermediate": intermediate,
            },
        )
        self._checkpoint(CheckpointPhase.MODEL_RESPONSE)

    async def _request_terminal_summary(self) -> None:
        """Use one tool-free grace call to explain a run stopped by its step budget."""
        try:
            messages = self._build_messages()
            messages.append(
                Message(
                    role=MessageRole.SYSTEM,
                    content=(
                        "The tool-capable execution budget is exhausted. Do not call tools. "
                        "Provide a concise factual final summary of completed work, known "
                        "verification results, and anything still unfinished. Do not claim "
                        "success without evidence."
                    ),
                )
            )
            stream = getattr(self._provider, "stream", None)
            if callable(stream):
                response = cast(
                    ModelResponse,
                    await stream(messages, [], self._record_delta),
                )
            else:
                response = await self._provider.complete(messages, [])
        except (
            ContextBudgetError,
            ModelProtocolError,
            ProviderRequestError,
            StreamInterruptedError,
        ):
            return
        if response.tool_calls or not response.content:
            return
        self._record_response(response)

    def _deliver_pending_instructions(self) -> None:
        self._deliver_instructions(self._instruction_queue.drain())

    def _deliver_instructions(self, instructions: Sequence[RuntimeInstruction]) -> None:
        for instruction in instructions:
            self._prior_history.append(
                Message(role=MessageRole.USER, content=instruction.content)
            )
            self._emit(
                EventKind.INSTRUCTION_DELIVERED,
                {"instruction_id": instruction.id, "content": instruction.content},
            )

    async def _execute_actions(
        self,
        actions: Sequence[Action],
        *,
        verification: bool = False,
    ) -> None:
        for action in actions:
            self._guard_runtime()
            instructions_changed = self._apply_scoped_instructions(action)
            self._checkpoint(CheckpointPhase.TOOL_EXECUTING, pending_action=action)
            self._actions.append(action)
            self._emit(
                EventKind.ACTION_REQUESTED,
                {"action": action.model_dump(mode="json"), "verification": verification},
            )
            if instructions_changed and not verification:
                observation = Observation(
                    action_id=action.id,
                    status=ObservationStatus.ERROR,
                    summary="Scoped AGENTS.md rules loaded; review them and reissue the action.",
                    content=(
                        "The action was not executed because more specific repository "
                        "instructions became active."
                    ),
                    duration_ms=0,
                )
                self._record_observation(action, observation, verification=False)
                self._checkpoint(CheckpointPhase.TOOL_FINISHED)
                return
            capacity_error = self._skill_capacity_error(action)
            if capacity_error is None:
                observation = await self._registry.dispatch(action)
            else:
                observation = capacity_error
            stored = self._record_observation(action, observation, verification=verification)
            if action.tool_name == "load_skill" and observation.status is ObservationStatus.SUCCESS:
                self._activate_skill(observation, trigger="model")
            if action.tool_name == "update_plan":
                active = action.arguments.get("active_step_id")
                self._active_step_id = active if isinstance(active, str) else None
                self._emit_plan()
            step_ids = (
                (self._active_step_id,)
                if self._active_step_id is not None and action.tool_name != "update_plan"
                else ()
            )
            self._ledger.record(
                action,
                observation,
                step_ids=step_ids,
                source_event_id=stored.event.id,
                verification=verification,
            )
            if step_ids:
                self._advance_plan_if_needed(step_ids[0])
            if observation.status is ObservationStatus.DENIED:
                raise _TerminalRun(StopReason.PERMISSION_DENIED)
            if observation.status is not ObservationStatus.SUCCESS:
                self._unresolved_errors.append(observation.summary)
            self._checkpoint(CheckpointPhase.TOOL_FINISHED)

    def _skill_capacity_error(self, action: Action) -> Observation | None:
        if action.tool_name != "load_skill":
            return None
        name = action.arguments.get("name")
        if not isinstance(name, str) or name in self._active_skills:
            return None
        if len(self._active_skills) < MAX_ACTIVE_SKILLS:
            return None
        return Observation(
            action_id=action.id,
            status=ObservationStatus.ERROR,
            summary=(
                f"active Skill limit ({MAX_ACTIVE_SKILLS}) reached; "
                f"{name} was not loaded"
            ),
            content="",
            duration_ms=0,
            metadata={"skill_name": name},
        )

    def _record_observation(
        self,
        action: Action,
        observation: Observation,
        *,
        verification: bool,
    ) -> StoredEvent:
        public_observation = (
            observation.model_copy(update={"content": ""})
            if action.tool_name == "load_skill"
            else observation
        )
        self._observations.append(public_observation)
        self._completed_action_ids.append(action.id)
        stored = self._emit(
            EventKind.OBSERVATION_RECEIVED,
            {
                "observation": public_observation.model_dump(mode="json"),
                "verification": verification,
            },
        )
        if not verification:
            self._history.append(
                Message(
                    role=MessageRole.TOOL,
                    content=public_observation.model_dump_json(),
                    tool_call_id=action.id,
                )
            )
        return stored

    def _activate_skill(self, observation: Observation, *, trigger: str) -> None:
        name = observation.metadata.get("skill_name")
        if not isinstance(name, str) or name in self._active_skills:
            return
        self._active_skills[name] = observation.content
        self._emit(
            EventKind.SKILL_APPLIED,
            {
                "name": name,
                "source": observation.metadata.get("source", ""),
                "scope": observation.metadata.get("scope", ""),
                "trigger": trigger,
                "summary": observation.metadata.get("summary", ""),
                "resource_count": observation.metadata.get("resource_count", 0),
            },
        )

    def _prepare_explicit_skill(self, task: str) -> None:
        try:
            invocation = parse_skill_invocation(task)
        except SkillInvocationError as error:
            self._final_answer = str(error)
            raise _TerminalRun(StopReason.TOOL_ERROR) from error
        if invocation is None:
            return
        try:
            loaded = self._skill_catalog.load(invocation.name, allow_hidden=True)
        except SkillCatalogError as error:
            self._final_answer = f"无法加载 Skill：{error}"
            raise _TerminalRun(StopReason.TOOL_ERROR) from error
        descriptor = loaded.descriptor
        observation = Observation(
            action_id=f"explicit-skill-{descriptor.name}",
            status=ObservationStatus.SUCCESS,
            summary=f"Loaded Skill: {descriptor.name}",
            content=render_loaded_skill(loaded),
            metadata={
                "skill_name": descriptor.name,
                "source": descriptor.source,
                "scope": descriptor.scope.value,
                "summary": descriptor.description,
                "resource_count": len(loaded.resources),
            },
            duration_ms=0,
        )
        self._activate_skill(observation, trigger="explicit")
        self._model_task = invocation.arguments or (
            f"Apply the explicitly selected Skill: {descriptor.name}."
        )

    def _apply_scoped_instructions(self, action: Action) -> bool:
        target = action.arguments.get("path")
        if not isinstance(target, str) or not target.strip():
            return False
        try:
            bundle = self._instruction_resolver.resolve_for(target)
        except ProjectInstructionsError:
            # The tool registry will turn an unsafe or invalid path into a recoverable
            # observation. Scoped instruction discovery must not terminate the run first.
            return False
        sources = tuple(document.source for document in bundle.documents)
        changed = sources != self._instruction_sources
        self._project_instructions = bundle.render()
        self._instruction_sources = sources
        self._ledger.record_instruction_sources(action.id, bundle.documents)
        self._emit(
            EventKind.INSTRUCTIONS_APPLIED,
            {
                "action_id": action.id,
                "target": target,
                "documents": [
                    {
                        "source": document.source,
                        "scope": document.scope,
                        "summary": document.summary,
                    }
                    for document in bundle.documents
                ],
            },
        )
        return changed

    async def _verify_changes(self) -> AgentRunResult:
        state = self._state_required()
        state.begin_verification()
        self._checkpoint(CheckpointPhase.VERIFYING)
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
        if self._allowed_change_paths is not None:
            scope = assess_change_scope(
                changed_paths=[change.path for change in self._context.changeset.changes],
                allowed_paths=self._allowed_change_paths,
            )
            if not scope.allowed:
                paths = ", ".join(scope.unrelated_paths)
                self._unresolved_errors.append(f"Changes outside allowed scope: {paths}")
                self._verification = self._verification.model_copy(
                    update={
                        "passed": False,
                        "level": VerificationLevel.FAILED,
                        "stop_reason": StopReason.VERIFICATION_FAILED,
                    }
                )
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
        if (
            self._limits.max_steps is not None
            and self._state_required().steps_taken >= self._limits.max_steps
        ):
            raise _TerminalRun(StopReason.STEP_LIMIT)

    def _guard_runtime(self) -> None:
        if self._cancel_event.is_set():
            raise _TerminalRun(StopReason.USER_STOPPED)
        if (
            self._limits.max_wall_time_seconds is not None
            and self._clock() - self._started_at >= self._limits.max_wall_time_seconds
        ):
            raise _TerminalRun(StopReason.TIME_LIMIT)

    def _finish(self, reason: StopReason, *, verified: bool | None) -> AgentRunResult:
        state = self._state_required()
        if state.can_continue:
            state.finish(reason, verified=verified)
        self._emit_state()
        if self._context.changeset.changes:
            snapshot = self._context.changeset.snapshot()
            self._emit(EventKind.CHANGESET_RECORDED, snapshot.model_dump(mode="json"))
        self._emit(
            EventKind.RUN_FINISHED,
            {
                "status": state.status.value,
                "stop_reason": reason.value,
                "verified": verified,
                "final_answer": self._final_answer,
            },
        )
        terminal_phase = (
            CheckpointPhase.COMPLETED
            if reason in {StopReason.COMPLETED, StopReason.PARTIALLY_VERIFIED}
            else CheckpointPhase.INTERRUPTED
            if reason in {StopReason.USER_STOPPED, StopReason.APP_INTERRUPTED}
            else CheckpointPhase.FAILED
        )
        self._checkpoint(terminal_phase)
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

    def _checkpoint(
        self,
        phase: CheckpointPhase,
        *,
        pending_action: Action | None = None,
    ) -> RunCheckpoint:
        return self._checkpoint_store.save(
            RunCheckpoint(
                run_id=self._run_id,
                task=self._task,
                phase=phase,
                messages=tuple((*self._prior_history, *self._history)),
                pending_action=pending_action,
                completed_action_ids=tuple(self._completed_action_ids),
                active_skill_names=tuple(self._active_skills),
                changeset_id=self._run_id if self._context.changeset.changes else None,
            )
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

    def _advance_plan_if_needed(self, step_id: str) -> None:
        if self._ledger.get_step(step_id).status is not StepStatus.PASSED:
            self._emit_plan()
            return
        next_step = next(
            (step for step in self._ledger.steps if step.status is StepStatus.PENDING),
            None,
        )
        self._active_step_id = next_step.id if next_step is not None else None
        if next_step is not None:
            self._ledger.mark_running(next_step.id)
        self._emit_plan()

    def _emit_plan(self) -> StoredEvent:
        return self._emit(
            EventKind.PLAN_UPDATED,
            {
                "active_step_id": self._active_step_id,
                "steps": [step.model_dump(mode="json") for step in self._ledger.steps],
                "evidence": [
                    item.model_dump(mode="json") for item in self._ledger.evidence
                ],
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
