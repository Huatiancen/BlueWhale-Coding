from pathlib import Path

import pytest

from bluewhale_agent.domain.models import Observation, ObservationStatus, StopReason
from bluewhale_agent.runtime.paths import WorkspacePaths
from bluewhale_agent.verification.discovery import (
    VerificationKind,
    discover_verification_commands,
)
from bluewhale_agent.verification.gate import (
    VerificationCommand,
    VerificationGate,
    VerificationLevel,
    VerificationOutcome,
    VerificationResultStatus,
    assess_change_scope,
    error_fingerprint,
)


def observation(
    status: ObservationStatus,
    *,
    summary: str,
    content: str = "",
    exit_code: int | None = None,
) -> Observation:
    metadata: dict[str, object] = {}
    if exit_code is not None:
        metadata["exit_code"] = exit_code
    return Observation(
        action_id="verification",
        status=status,
        summary=summary,
        content=content,
        metadata=metadata,
        duration_ms=12,
    )


def discover(tmp_path: Path) -> tuple[VerificationCommand, ...]:
    return discover_verification_commands(WorkspacePaths(tmp_path))


def test_discovers_declared_pytest_configuration(tmp_path: Path) -> None:
    (tmp_path / "pyproject.toml").write_text(
        "[project]\nname = 'demo'\n\n[tool.pytest.ini_options]\ntestpaths = ['tests']\n",
        encoding="utf-8",
    )

    commands = discover(tmp_path)

    assert [(item.command, item.kind, item.source) for item in commands] == [
        ("python -m pytest -q", VerificationKind.TEST, "pyproject.toml")
    ]


def test_node_discovery_uses_only_declared_standard_scripts(tmp_path: Path) -> None:
    (tmp_path / "package.json").write_text(
        """{
          "scripts": {
            "postinstall": "download-something",
            "test": "vitest run",
            "build": "vite build",
            "release": "publish-something"
          }
        }""",
        encoding="utf-8",
    )

    commands = discover(tmp_path)

    assert [(item.command, item.kind) for item in commands] == [
        ("npm run test", VerificationKind.TEST),
        ("npm run build", VerificationKind.BUILD),
    ]
    assert all("install" not in item.command and "release" not in item.command for item in commands)


@pytest.mark.parametrize(
    ("manifest", "expected"),
    [("Cargo.toml", "cargo test"), ("go.mod", "go test ./...")],
)
def test_discovers_standard_compiled_language_tests(
    tmp_path: Path, manifest: str, expected: str
) -> None:
    (tmp_path / manifest).write_text("project declaration", encoding="utf-8")

    commands = discover(tmp_path)

    assert [item.command for item in commands] == [expected]


def test_project_without_test_declaration_has_no_guessed_command(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("no test setup", encoding="utf-8")

    assert discover(tmp_path) == ()


@pytest.mark.asyncio
async def test_first_failure_can_be_repaired_and_verified() -> None:
    responses = iter(
        [
            observation(
                ObservationStatus.ERROR,
                summary="Command exited with code 1: pytest",
                content="assert 1 == 2",
                exit_code=1,
            ),
            observation(
                ObservationStatus.SUCCESS,
                summary="Command exited with code 0: pytest",
                content="1 passed",
                exit_code=0,
            ),
        ]
    )
    repairs: list[int] = []

    async def runner(_: VerificationCommand) -> Observation:
        return next(responses)

    async def repair(_results: tuple[object, ...], attempt: int) -> None:
        repairs.append(attempt)

    outcome = await VerificationGate(max_repair_attempts=2).run(
        (VerificationCommand(command="pytest -q", kind=VerificationKind.TEST, source="test"),),
        runner,
        repair,
    )

    assert outcome.passed is True
    assert outcome.level is VerificationLevel.PUBLIC_PASSED
    assert outcome.completion_claim_supported is True
    assert outcome.stop_reason is StopReason.COMPLETED
    assert outcome.rounds == 2
    assert outcome.repair_attempts == 1
    assert repairs == [1]
    assert outcome.latest_results[0].status is VerificationResultStatus.PASSED


@pytest.mark.asyncio
async def test_consecutive_equivalent_failures_stop_as_no_progress() -> None:
    responses = iter(
        [
            observation(
                ObservationStatus.ERROR,
                summary="failed at 2026-08-27T10:15:01Z",
                content="/tmp/pytest-1/test_app.py:41:7: AssertionError",
                exit_code=1,
            ),
            observation(
                ObservationStatus.ERROR,
                summary="failed at 2026-08-27T10:16:22Z",
                content="/private/tmp/pytest-99/test_app.py:87:2: AssertionError",
                exit_code=1,
            ),
        ]
    )
    repairs: list[int] = []

    async def runner(_: VerificationCommand) -> Observation:
        return next(responses)

    async def repair(_results: tuple[object, ...], attempt: int) -> None:
        repairs.append(attempt)

    outcome = await VerificationGate(max_repair_attempts=2).run(
        (VerificationCommand(command="pytest -q", kind=VerificationKind.TEST, source="test"),),
        runner,
        repair,
    )

    assert outcome.passed is False
    assert outcome.stop_reason is StopReason.NO_PROGRESS
    assert outcome.level is VerificationLevel.FAILED
    assert outcome.rounds == 2
    assert repairs == [1]
    assert outcome.fingerprints[0] == outcome.fingerprints[1]


def test_error_fingerprint_ignores_volatile_locations_and_timestamps() -> None:
    first = "2026-08-27 10:15:01 /tmp/run-a/test_app.py:12:4 ValueError"
    second = "2026-08-27 11:22:33 /private/tmp/run-b/test_app.py:98:17 ValueError"

    assert error_fingerprint(first) == error_fingerprint(second)


@pytest.mark.asyncio
async def test_gate_never_exceeds_two_repair_rounds() -> None:
    responses = iter(
        [
            observation(ObservationStatus.ERROR, summary="failure A", exit_code=1),
            observation(ObservationStatus.ERROR, summary="failure B", exit_code=1),
            observation(ObservationStatus.ERROR, summary="failure C", exit_code=1),
        ]
    )
    repairs: list[int] = []

    async def runner(_: VerificationCommand) -> Observation:
        return next(responses)

    async def repair(_results: tuple[object, ...], attempt: int) -> None:
        repairs.append(attempt)

    outcome = await VerificationGate(max_repair_attempts=2).run(
        (VerificationCommand(command="pytest -q", kind=VerificationKind.TEST, source="test"),),
        runner,
        repair,
    )

    assert outcome.stop_reason is StopReason.VERIFICATION_FAILED
    assert outcome.rounds == 3
    assert outcome.repair_attempts == 2
    assert repairs == [1, 2]


@pytest.mark.asyncio
async def test_default_gate_allows_three_repair_attempts() -> None:
    responses = iter(
        observation(ObservationStatus.ERROR, summary=f"failure {index}", exit_code=1)
        for index in range(4)
    )
    repairs: list[int] = []

    async def runner(_: VerificationCommand) -> Observation:
        return next(responses)

    async def repair(_results: tuple[object, ...], attempt: int) -> None:
        repairs.append(attempt)

    outcome = await VerificationGate().run(
        (VerificationCommand(command="pytest -q", kind=VerificationKind.TEST, source="test"),),
        runner,
        repair,
    )

    assert outcome.repair_attempts == 3
    assert repairs == [1, 2, 3]


@pytest.mark.asyncio
async def test_missing_verification_command_is_partially_verified() -> None:
    repair_called = False

    async def runner(_: VerificationCommand) -> Observation:
        return observation(
            ObservationStatus.ERROR,
            summary="Command could not be started: No such file or directory",
        )

    async def repair(_results: tuple[object, ...], _attempt: int) -> None:
        nonlocal repair_called
        repair_called = True

    outcome = await VerificationGate().run(
        (VerificationCommand(command="pytest -q", kind=VerificationKind.TEST, source="test"),),
        runner,
        repair,
    )

    assert outcome.stop_reason is StopReason.PARTIALLY_VERIFIED
    assert outcome.level is VerificationLevel.PARTIAL
    assert outcome.latest_results[0].status is VerificationResultStatus.UNAVAILABLE
    assert repair_called is False


@pytest.mark.asyncio
async def test_no_discovered_commands_is_partially_verified() -> None:
    async def runner(_: VerificationCommand) -> Observation:
        raise AssertionError("runner must not be called")

    outcome = await VerificationGate().run((), runner)

    assert outcome.passed is False
    assert outcome.stop_reason is StopReason.PARTIALLY_VERIFIED
    assert outcome.rounds == 0
    assert outcome.level is VerificationLevel.UNVERIFIED
    assert outcome.completion_claim_supported is False


def test_hidden_verification_upgrades_public_outcome_to_full() -> None:
    public = VerificationOutcome(
        passed=True,
        level=VerificationLevel.PUBLIC_PASSED,
        stop_reason=StopReason.COMPLETED,
        rounds=1,
        repair_attempts=0,
    )

    full = public.with_hidden_verification(True)

    assert full.level is VerificationLevel.FULL_PASSED
    assert full.passed is True


def test_change_scope_reports_paths_outside_allowlist() -> None:
    result = assess_change_scope(
        changed_paths=("src/app.py", "README.md", "tests/test_app.py"),
        allowed_paths=("src/app.py", "tests/"),
    )

    assert result.allowed is False
    assert result.unrelated_paths == ("README.md",)
