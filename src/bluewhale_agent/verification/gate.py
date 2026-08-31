"""Bounded verification with normalized failure and no-progress detection."""

from __future__ import annotations

import hashlib
import re
from collections.abc import Awaitable, Callable, Sequence
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.domain.models import Observation, ObservationStatus, StopReason
from bluewhale_agent.verification.discovery import VerificationCommand

VerificationRunner = Callable[[VerificationCommand], Awaitable[Observation]]
RepairCallback = Callable[[tuple["VerificationResult", ...], int], Awaitable[None]]


class VerificationResultStatus(StrEnum):
    """Normalized outcomes independent of a command runner implementation."""

    PASSED = "passed"
    FAILED = "failed"
    UNAVAILABLE = "unavailable"
    TIMEOUT = "timeout"
    DENIED = "denied"


class VerificationLevel(StrEnum):
    """Evidence grade shown independently from the run's lifecycle status."""

    UNVERIFIED = "unverified"
    PARTIAL = "partial"
    PUBLIC_PASSED = "public_passed"
    FULL_PASSED = "full_passed"
    FAILED = "failed"


class VerificationResult(BaseModel):
    """One repository verification command and its normalized observation."""

    model_config = ConfigDict(frozen=True)

    command: VerificationCommand
    status: VerificationResultStatus
    summary: str
    content: str = ""
    exit_code: int | None = None
    duration_ms: int = Field(ge=0)
    fingerprint: str | None = None


class VerificationOutcome(BaseModel):
    """Final decision plus the evidence needed by the session controller and GUI."""

    model_config = ConfigDict(frozen=True)

    passed: bool
    level: VerificationLevel = VerificationLevel.UNVERIFIED
    stop_reason: StopReason
    rounds: int = Field(ge=0)
    repair_attempts: int = Field(ge=0)
    results: tuple[VerificationResult, ...] = ()
    latest_results: tuple[VerificationResult, ...] = ()
    fingerprints: tuple[str, ...] = ()

    @property
    def completion_claim_supported(self) -> bool:
        return self.level in {
            VerificationLevel.PUBLIC_PASSED,
            VerificationLevel.FULL_PASSED,
        }

    def with_hidden_verification(self, passed: bool) -> VerificationOutcome:
        if passed and self.passed:
            return self.model_copy(update={"level": VerificationLevel.FULL_PASSED})
        return self.model_copy(
            update={
                "passed": False,
                "level": VerificationLevel.FAILED,
                "stop_reason": StopReason.VERIFICATION_FAILED,
            }
        )


class ChangeScopeAssessment(BaseModel):
    model_config = ConfigDict(frozen=True)

    allowed: bool
    unrelated_paths: tuple[str, ...] = ()


class VerificationGate:
    """Run verification and stop bounded repair loops that make no progress."""

    def __init__(self, *, max_repair_attempts: int = 3) -> None:
        if max_repair_attempts < 0:
            raise ValueError("max_repair_attempts must not be negative")
        self._max_repair_attempts = max_repair_attempts

    async def run(
        self,
        commands: Sequence[VerificationCommand],
        runner: VerificationRunner,
        repair: RepairCallback | None = None,
    ) -> VerificationOutcome:
        if not commands:
            return VerificationOutcome(
                passed=False,
                level=VerificationLevel.UNVERIFIED,
                stop_reason=StopReason.PARTIALLY_VERIFIED,
                rounds=0,
                repair_attempts=0,
            )

        all_results: list[VerificationResult] = []
        fingerprints: list[str] = []
        repair_attempts = 0
        rounds = 0

        while True:
            rounds += 1
            round_results: list[VerificationResult] = []
            for command in commands:
                observed = await runner(command)
                round_results.append(self._to_result(command, observed))
            latest = tuple(round_results)
            all_results.extend(latest)

            if all(result.status is VerificationResultStatus.PASSED for result in latest):
                return self._outcome(
                    passed=True,
                    reason=StopReason.COMPLETED,
                    rounds=rounds,
                    repair_attempts=repair_attempts,
                    results=all_results,
                    latest=latest,
                    fingerprints=fingerprints,
                )

            if any(result.status is VerificationResultStatus.DENIED for result in latest):
                return self._outcome(
                    passed=False,
                    reason=StopReason.PERMISSION_DENIED,
                    rounds=rounds,
                    repair_attempts=repair_attempts,
                    results=all_results,
                    latest=latest,
                    fingerprints=fingerprints,
                )

            if any(result.status is VerificationResultStatus.UNAVAILABLE for result in latest):
                return self._outcome(
                    passed=False,
                    reason=StopReason.PARTIALLY_VERIFIED,
                    rounds=rounds,
                    repair_attempts=repair_attempts,
                    results=all_results,
                    latest=latest,
                    fingerprints=fingerprints,
                )

            round_fingerprint = _round_fingerprint(latest)
            fingerprints.append(round_fingerprint)
            if len(fingerprints) >= 2 and fingerprints[-1] == fingerprints[-2]:
                return self._outcome(
                    passed=False,
                    reason=StopReason.NO_PROGRESS,
                    rounds=rounds,
                    repair_attempts=repair_attempts,
                    results=all_results,
                    latest=latest,
                    fingerprints=fingerprints,
                )

            if repair is None or repair_attempts >= self._max_repair_attempts:
                return self._outcome(
                    passed=False,
                    reason=StopReason.VERIFICATION_FAILED,
                    rounds=rounds,
                    repair_attempts=repair_attempts,
                    results=all_results,
                    latest=latest,
                    fingerprints=fingerprints,
                )

            repair_attempts += 1
            await repair(latest, repair_attempts)

    @staticmethod
    def _to_result(command: VerificationCommand, observation: Observation) -> VerificationResult:
        status = _result_status(observation)
        diagnostic = "\n".join(part for part in (observation.summary, observation.content) if part)
        fingerprint = None
        if status in {VerificationResultStatus.FAILED, VerificationResultStatus.TIMEOUT}:
            fingerprint = error_fingerprint(diagnostic)
        exit_code = observation.metadata.get("exit_code")
        return VerificationResult(
            command=command,
            status=status,
            summary=observation.summary,
            content=observation.content,
            exit_code=exit_code if isinstance(exit_code, int) else None,
            duration_ms=observation.duration_ms,
            fingerprint=fingerprint,
        )

    @staticmethod
    def _outcome(
        *,
        passed: bool,
        reason: StopReason,
        rounds: int,
        repair_attempts: int,
        results: list[VerificationResult],
        latest: tuple[VerificationResult, ...],
        fingerprints: list[str],
    ) -> VerificationOutcome:
        return VerificationOutcome(
            passed=passed,
            level=(
                VerificationLevel.PUBLIC_PASSED
                if passed
                else VerificationLevel.PARTIAL
                if reason is StopReason.PARTIALLY_VERIFIED
                else VerificationLevel.FAILED
            ),
            stop_reason=reason,
            rounds=rounds,
            repair_attempts=repair_attempts,
            results=tuple(results),
            latest_results=latest,
            fingerprints=tuple(fingerprints),
        )


def error_fingerprint(diagnostic: str) -> str:
    """Hash the stable structure of an error while removing volatile run details."""

    normalized = diagnostic.lower()
    timestamp_pattern = r"\b\d{4}-\d{2}-\d{2}[t ]\d{2}:\d{2}:\d{2}(?:\.\d+)?z?\b"
    normalized = re.sub(timestamp_pattern, "<time>", normalized)
    normalized = re.sub(r"(?:/private)?/tmp/\S+", "<tmp>", normalized)
    normalized = re.sub(r"(?<=\w):\d+(?::\d+)?\b", ":<line>", normalized)
    normalized = re.sub(r"\bline\s+\d+\b", "line <n>", normalized)
    normalized = re.sub(r"\b\d+(?:\.\d+)?s\b", "<duration>", normalized)
    normalized = " ".join(normalized.split())
    return hashlib.sha256(normalized.encode("utf-8")).hexdigest()


def assess_change_scope(
    *,
    changed_paths: Sequence[str],
    allowed_paths: Sequence[str],
) -> ChangeScopeAssessment:
    """Report changes outside exact files or explicitly allowed directory prefixes."""

    normalized = tuple(
        (path.strip("/"), path.endswith("/"))
        for path in allowed_paths
        if path.strip("/")
    )
    unrelated = tuple(
        sorted(
            path
            for path in changed_paths
            if not any(
                path == allowed or (is_directory and path.startswith(f"{allowed}/"))
                for allowed, is_directory in normalized
            )
        )
    )
    return ChangeScopeAssessment(allowed=not unrelated, unrelated_paths=unrelated)


def _result_status(observation: Observation) -> VerificationResultStatus:
    if observation.status is ObservationStatus.SUCCESS:
        return VerificationResultStatus.PASSED
    if observation.status is ObservationStatus.TIMEOUT:
        return VerificationResultStatus.TIMEOUT
    if observation.status is ObservationStatus.DENIED:
        return VerificationResultStatus.DENIED
    summary = observation.summary.lower()
    if any(
        marker in summary
        for marker in (
            "could not be started",
            "command not found",
            "no such file or directory",
            "not recognized as",
        )
    ):
        return VerificationResultStatus.UNAVAILABLE
    return VerificationResultStatus.FAILED


def _round_fingerprint(results: Sequence[VerificationResult]) -> str:
    components = [
        f"{result.command.command}:{result.fingerprint}"
        for result in results
        if result.fingerprint is not None
    ]
    return hashlib.sha256("\n".join(components).encode("utf-8")).hexdigest()
