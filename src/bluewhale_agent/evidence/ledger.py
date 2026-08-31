"""Deterministic evidence mapping and task-step assessment."""

from __future__ import annotations

import hashlib
from collections.abc import Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.context.instructions import InstructionDocument
from bluewhale_agent.domain.models import Action, Observation, ObservationStatus


class EvidenceKind(StrEnum):
    """Stable facts that local tools can establish."""

    FILE_READ = "file_read"
    SEARCH_MATCH = "search_match"
    FILE_DIFF = "file_diff"
    COMMAND_RESULT = "command_result"
    TEST_RESULT = "test_result"
    INSTRUCTION_RULE = "instruction_rule"


class StepRequirement(StrEnum):
    """Evidence rule attached to a model-proposed task step."""

    LOCATE = "locate"
    MODIFY = "modify"
    COMMAND = "command"
    TEST = "test"
    FIX = "fix"


class StepStatus(StrEnum):
    """Task-step states controlled by the ledger and controller."""

    PENDING = "pending"
    RUNNING = "running"
    PASSED = "passed"
    FAILED = "failed"
    SKIPPED = "skipped"


class ReportOutcome(StrEnum):
    """Deterministic aggregate assessment for a ledger report."""

    COMPLETED = "completed"
    PARTIAL = "partial"
    INCOMPLETE = "incomplete"


class Evidence(BaseModel):
    """One immutable fact derived from a local Observation."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    kind: EvidenceKind
    source_event_id: str = Field(min_length=1)
    claim: str = Field(min_length=1)
    verified: bool
    metadata: dict[str, object] = Field(default_factory=dict)


class TaskStep(BaseModel):
    """A proposed step whose status is updated only by deterministic rules."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(min_length=1)
    description: str = Field(min_length=1)
    requirement: StepRequirement
    status: StepStatus = StepStatus.PENDING
    evidence_ids: tuple[str, ...] = ()


class LedgerReport(BaseModel):
    """Stable report sections suitable for the GUI and final response."""

    model_config = ConfigDict(frozen=True)

    outcome: ReportOutcome
    completed: tuple[TaskStep, ...]
    incomplete: tuple[TaskStep, ...]
    insufficiently_verified: tuple[TaskStep, ...]
    evidence: tuple[Evidence, ...]

    def render(self) -> str:
        lines = ["# Evidence report", f"Outcome: {self.outcome.value}"]
        self._append_steps(lines, "Completed steps", self.completed)
        self._append_steps(
            lines,
            "Insufficiently verified steps",
            self.insufficiently_verified,
        )
        self._append_steps(lines, "Incomplete steps", self.incomplete)

        lines.append("\n## Command results")
        commands = [
            item
            for item in self.evidence
            if item.kind in {EvidenceKind.COMMAND_RESULT, EvidenceKind.TEST_RESULT}
        ]
        if not commands:
            lines.append("- None")
        else:
            for item in commands:
                verdict = "verified" if item.verified else "not verified"
                exit_code = item.metadata.get("exit_code")
                lines.append(f"- {item.claim} ({verdict}, exit_code={exit_code})")
        return "\n".join(lines)

    @staticmethod
    def _append_steps(lines: list[str], title: str, steps: tuple[TaskStep, ...]) -> None:
        lines.append(f"\n## {title}")
        if steps:
            lines.extend(f"- [{step.id}] {step.description}" for step in steps)
        else:
            lines.append("- None")


class EvidenceLedger:
    """Own task status and accept facts only from local tool observations."""

    def __init__(self) -> None:
        self._steps: dict[str, TaskStep] = {}
        self._evidence: dict[str, Evidence] = {}
        self._model_statements: list[str] = []

    @property
    def steps(self) -> tuple[TaskStep, ...]:
        return tuple(self._steps.values())

    @property
    def evidence(self) -> tuple[Evidence, ...]:
        return tuple(self._evidence.values())

    @property
    def model_statements(self) -> tuple[str, ...]:
        return tuple(self._model_statements)

    def add_step(
        self,
        step_id: str,
        description: str,
        requirement: StepRequirement,
    ) -> TaskStep:
        if step_id in self._steps:
            raise ValueError(f"Task step already exists: {step_id}")
        step = TaskStep(id=step_id, description=description, requirement=requirement)
        self._steps[step_id] = step
        return step

    def set_plan(self, steps: Sequence[TaskStep]) -> tuple[TaskStep, ...]:
        """Replace the proposed plan while preserving compatible evidence state."""

        if len({step.id for step in steps}) != len(steps):
            raise ValueError("Task step identifiers must be unique")
        updated: dict[str, TaskStep] = {}
        for proposed in steps:
            current = self._steps.get(proposed.id)
            if (
                current is not None
                and current.description == proposed.description
                and current.requirement is proposed.requirement
            ):
                updated[proposed.id] = current
            else:
                updated[proposed.id] = proposed.model_copy(
                    update={"status": StepStatus.PENDING, "evidence_ids": ()}
                )
        self._steps = updated
        return self.steps

    def get_step(self, step_id: str) -> TaskStep:
        try:
            return self._steps[step_id]
        except KeyError as exc:
            raise KeyError(f"Unknown task step: {step_id}") from exc

    def record_model_statement(self, statement: str) -> None:
        """Store untrusted model prose without treating it as evidence."""

        if statement:
            self._model_statements.append(statement)

    def record_instruction_sources(
        self,
        action_id: str,
        documents: Sequence[InstructionDocument],
    ) -> tuple[Evidence, ...]:
        recorded: list[Evidence] = []
        for document in documents:
            identity = f"{action_id}:{document.source}"
            item = Evidence(
                id=f"instruction:{hashlib.sha256(identity.encode()).hexdigest()[:20]}",
                kind=EvidenceKind.INSTRUCTION_RULE,
                source_event_id=action_id,
                claim=f"Applied project instructions from {document.source}",
                verified=True,
                metadata={
                    "action_id": action_id,
                    "source": document.source,
                    "scope": document.scope,
                    "summary": document.summary,
                },
            )
            recorded.append(self._evidence.setdefault(item.id, item))
        return tuple(recorded)

    def record(
        self,
        action: Action,
        observation: Observation,
        *,
        step_ids: Sequence[str] = (),
        source_event_id: str | None = None,
        verification: bool = False,
    ) -> tuple[Evidence, ...]:
        if action.id != observation.action_id:
            raise ValueError("Action and Observation identifiers do not match")
        for step_id in step_ids:
            self.get_step(step_id)

        event_id = source_event_id or observation.action_id
        derived = self._derive(action, observation, event_id, verification)
        recorded: list[Evidence] = []
        for item in derived:
            stored = self._evidence.setdefault(item.id, item)
            recorded.append(stored)
            for step_id in step_ids:
                self._attach(step_id, stored.id)

        for step_id in step_ids:
            self._refresh(step_id)
        return tuple(recorded)

    def mark_running(self, step_id: str) -> TaskStep:
        step = self.get_step(step_id)
        if step.status is not StepStatus.PENDING:
            raise ValueError(f"Only pending steps can start: {step_id}")
        updated = step.model_copy(update={"status": StepStatus.RUNNING})
        self._steps[step_id] = updated
        return updated

    def mark_failed(self, step_id: str) -> TaskStep:
        return self._set_terminal_status(step_id, StepStatus.FAILED)

    def skip(self, step_id: str) -> TaskStep:
        return self._set_terminal_status(step_id, StepStatus.SKIPPED)

    def report(self) -> LedgerReport:
        completed = tuple(step for step in self.steps if step.status is StepStatus.PASSED)
        remaining = tuple(
            step
            for step in self.steps
            if step.status not in {StepStatus.PASSED, StepStatus.SKIPPED}
        )
        insufficient = tuple(step for step in remaining if step.evidence_ids)
        insufficient_ids = {step.id for step in insufficient}
        incomplete = tuple(step for step in remaining if step.id not in insufficient_ids)
        if self.steps and not remaining:
            outcome = ReportOutcome.COMPLETED
        elif completed or insufficient:
            outcome = ReportOutcome.PARTIAL
        else:
            outcome = ReportOutcome.INCOMPLETE
        return LedgerReport(
            outcome=outcome,
            completed=completed,
            incomplete=incomplete,
            insufficiently_verified=insufficient,
            evidence=self.evidence,
        )

    def _attach(self, step_id: str, evidence_id: str) -> None:
        step = self.get_step(step_id)
        if evidence_id in step.evidence_ids:
            return
        self._steps[step_id] = step.model_copy(
            update={"evidence_ids": (*step.evidence_ids, evidence_id)}
        )

    def _refresh(self, step_id: str) -> None:
        step = self.get_step(step_id)
        if step.status in {StepStatus.FAILED, StepStatus.SKIPPED}:
            return
        passed = self._step_passed(step)
        if passed:
            self._steps[step_id] = step.model_copy(update={"status": StepStatus.PASSED})
        elif step.status is StepStatus.PASSED:
            self._steps[step_id] = step.model_copy(update={"status": StepStatus.RUNNING})

    def _step_passed(self, step: TaskStep) -> bool:
        items = [self._evidence[evidence_id] for evidence_id in step.evidence_ids]
        if step.requirement is StepRequirement.LOCATE:
            return any(
                item.verified
                and item.kind in {EvidenceKind.FILE_READ, EvidenceKind.SEARCH_MATCH}
                for item in items
            )
        if step.requirement is StepRequirement.MODIFY:
            return any(
                item.verified and item.kind is EvidenceKind.FILE_DIFF for item in items
            )
        if step.requirement is StepRequirement.COMMAND:
            latest_command = next(
                (item for item in reversed(items) if item.kind is EvidenceKind.COMMAND_RESULT),
                None,
            )
            return latest_command is not None and latest_command.verified
        if step.requirement is StepRequirement.TEST:
            latest_test = next(
                (item for item in reversed(items) if item.kind is EvidenceKind.TEST_RESULT),
                None,
            )
            return latest_test is not None and latest_test.verified
        if step.requirement is StepRequirement.FIX:
            latest_diff = max(
                (
                    index
                    for index, item in enumerate(items)
                    if item.kind is EvidenceKind.FILE_DIFF and item.verified
                ),
                default=-1,
            )
            latest_test_entry = next(
                (
                    (index, item)
                    for index, item in reversed(list(enumerate(items)))
                    if item.kind is EvidenceKind.TEST_RESULT
                ),
                None,
            )
            return (
                latest_diff >= 0
                and latest_test_entry is not None
                and latest_test_entry[0] > latest_diff
                and latest_test_entry[1].verified
            )
        raise AssertionError(f"Unhandled step requirement: {step.requirement}")

    def _set_terminal_status(self, step_id: str, status: StepStatus) -> TaskStep:
        step = self.get_step(step_id)
        if step.status is StepStatus.PASSED:
            raise ValueError(f"Passed steps cannot become {status.value}: {step_id}")
        updated = step.model_copy(update={"status": status})
        self._steps[step_id] = updated
        return updated

    @classmethod
    def _derive(
        cls,
        action: Action,
        observation: Observation,
        source_event_id: str,
        verification: bool,
    ) -> tuple[Evidence, ...]:
        if action.tool_name == "read_file" and observation.status is ObservationStatus.SUCCESS:
            return (
                cls._make_evidence(
                    EvidenceKind.FILE_READ,
                    source_event_id,
                    f"Read {observation.metadata.get('path', 'a workspace file')}",
                    True,
                    observation,
                ),
            )
        if action.tool_name == "search_text" and observation.status is ObservationStatus.SUCCESS:
            count = observation.metadata.get("count")
            if isinstance(count, int) and not isinstance(count, bool) and count > 0:
                return (
                    cls._make_evidence(
                        EvidenceKind.SEARCH_MATCH,
                        source_event_id,
                        f"Found {count} search matches",
                        True,
                        observation,
                    ),
                )
            return ()
        if action.tool_name in {"apply_patch", "write_file"}:
            return cls._derive_file_diff(action, observation, source_event_id)
        if action.tool_name == "run_command":
            return cls._derive_command(observation, source_event_id, verification)
        return ()

    @classmethod
    def _derive_file_diff(
        cls,
        action: Action,
        observation: Observation,
        source_event_id: str,
    ) -> tuple[Evidence, ...]:
        if observation.status is not ObservationStatus.SUCCESS:
            return ()
        before = observation.metadata.get("before_sha256")
        after = observation.metadata.get("after_sha256")
        created = action.tool_name == "write_file" and observation.metadata.get("created") is True
        changed_existing = isinstance(before, str) and isinstance(after, str) and before != after
        if not (created or changed_existing):
            return ()
        path = observation.metadata.get("path", "a workspace file")
        return (
            cls._make_evidence(
                EvidenceKind.FILE_DIFF,
                source_event_id,
                f"Changed {path}",
                True,
                observation,
            ),
        )

    @classmethod
    def _derive_command(
        cls,
        observation: Observation,
        source_event_id: str,
        verification: bool,
    ) -> tuple[Evidence, ...]:
        exit_code = observation.metadata.get("exit_code")
        succeeded = observation.status is ObservationStatus.SUCCESS and exit_code == 0
        argv = observation.metadata.get("argv")
        command = " ".join(str(item) for item in argv) if isinstance(argv, list) else "command"
        command_result = cls._make_evidence(
            EvidenceKind.COMMAND_RESULT,
            source_event_id,
            f"Executed {command}",
            succeeded,
            observation,
        )
        if not verification:
            return (command_result,)
        test_result = cls._make_evidence(
            EvidenceKind.TEST_RESULT,
            source_event_id,
            f"Verified with {command}",
            succeeded,
            observation,
        )
        return command_result, test_result

    @staticmethod
    def _make_evidence(
        kind: EvidenceKind,
        source_event_id: str,
        claim: str,
        verified: bool,
        observation: Observation,
    ) -> Evidence:
        digest = hashlib.sha256(f"{source_event_id}:{kind.value}".encode()).hexdigest()[:20]
        metadata = dict(observation.metadata)
        metadata.update(
            {
                "observation_status": observation.status.value,
                "duration_ms": observation.duration_ms,
            }
        )
        return Evidence(
            id=f"evidence-{digest}",
            kind=kind,
            source_event_id=source_event_id,
            claim=claim,
            verified=verified,
            metadata=metadata,
        )
