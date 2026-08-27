from collections.abc import Sequence

import pytest

from bluewhale_agent.domain.models import Action, Observation, ObservationStatus
from bluewhale_agent.evidence.ledger import (
    Evidence,
    EvidenceKind,
    EvidenceLedger,
    StepRequirement,
    StepStatus,
)


def observation(
    action_id: str,
    *,
    status: ObservationStatus = ObservationStatus.SUCCESS,
    summary: str = "ok",
    content: str = "",
    metadata: dict[str, object] | None = None,
) -> Observation:
    return Observation(
        action_id=action_id,
        status=status,
        summary=summary,
        content=content,
        metadata=metadata or {},
        duration_ms=10,
    )


def action(action_id: str, tool_name: str) -> Action:
    return Action(id=action_id, tool_name=tool_name, arguments={})


def evidence_kinds(items: Sequence[Evidence]) -> set[EvidenceKind]:
    return {item.kind for item in items}


def test_model_statement_cannot_mark_test_step_passed() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("test", "Run the tests", StepRequirement.TEST)

    ledger.record_model_statement("All tests passed successfully.")

    assert ledger.get_step("test").status is StepStatus.PENDING
    assert ledger.report().completed == ()
    assert ledger.model_statements == ("All tests passed successfully.",)


def test_successful_observations_map_to_stable_evidence_and_complete_steps() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("locate", "Locate the implementation", StepRequirement.LOCATE)
    ledger.add_step("modify", "Modify the implementation", StepRequirement.MODIFY)
    ledger.add_step("command", "Run a build command", StepRequirement.COMMAND)
    ledger.add_step("test", "Run the tests", StepRequirement.TEST)
    ledger.add_step("fix", "Fix and verify the bug", StepRequirement.FIX)

    read_evidence = ledger.record(
        action("read-1", "read_file"),
        observation("read-1", metadata={"path": "src/app.py"}),
        step_ids=("locate",),
    )
    diff_evidence = ledger.record(
        action("patch-1", "apply_patch"),
        observation(
            "patch-1",
            metadata={
                "path": "src/app.py",
                "before_sha256": "a" * 64,
                "after_sha256": "b" * 64,
            },
        ),
        step_ids=("modify", "fix"),
    )
    command_evidence = ledger.record(
        action("cmd-1", "run_command"),
        observation(
            "cmd-1",
            metadata={
                "argv": ["pytest", "-q"],
                "exit_code": 0,
                "artifact_path": ".bluewhale/artifacts/commands/1.log",
            },
        ),
        step_ids=("command", "test", "fix"),
        verification=True,
    )

    assert evidence_kinds(read_evidence) == {EvidenceKind.FILE_READ}
    assert evidence_kinds(diff_evidence) == {EvidenceKind.FILE_DIFF}
    assert evidence_kinds(command_evidence) == {
        EvidenceKind.COMMAND_RESULT,
        EvidenceKind.TEST_RESULT,
    }
    assert all(step.status is StepStatus.PASSED for step in ledger.steps)


def test_nonempty_search_is_evidence_but_empty_search_is_not() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("locate", "Find usages", StepRequirement.LOCATE)

    empty = ledger.record(
        action("search-0", "search_text"),
        observation("search-0", metadata={"count": 0}),
        step_ids=("locate",),
    )
    found = ledger.record(
        action("search-1", "search_text"),
        observation("search-1", metadata={"count": 2}),
        step_ids=("locate",),
    )

    assert empty == ()
    assert evidence_kinds(found) == {EvidenceKind.SEARCH_MATCH}
    assert ledger.get_step("locate").status is StepStatus.PASSED


@pytest.mark.parametrize(
    "status",
    [ObservationStatus.ERROR, ObservationStatus.TIMEOUT, ObservationStatus.DENIED],
)
def test_failed_timeout_and_denied_verification_are_never_positive(
    status: ObservationStatus,
) -> None:
    ledger = EvidenceLedger()
    ledger.add_step("test", "Run tests", StepRequirement.TEST)

    created = ledger.record(
        action("cmd-1", "run_command"),
        observation("cmd-1", status=status, metadata={"exit_code": 1}),
        step_ids=("test",),
        verification=True,
    )

    assert created
    assert all(item.verified is False for item in created)
    assert ledger.get_step("test").status is StepStatus.PENDING
    assert ledger.report().insufficiently_verified == (ledger.get_step("test"),)


def test_noop_or_untracked_file_write_does_not_create_diff_evidence() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("modify", "Modify code", StepRequirement.MODIFY)

    noop_patch = ledger.record(
        action("patch-1", "apply_patch"),
        observation(
            "patch-1",
            metadata={"before_sha256": None, "after_sha256": "a" * 64},
        ),
        step_ids=("modify",),
    )
    identical_write = ledger.record(
        action("write-1", "write_file"),
        observation(
            "write-1",
            metadata={
                "created": False,
                "before_sha256": None,
                "after_sha256": "a" * 64,
            },
        ),
        step_ids=("modify",),
    )

    assert noop_patch == ()
    assert identical_write == ()
    assert ledger.get_step("modify").status is StepStatus.PENDING


def test_report_separates_completed_incomplete_and_insufficient_steps() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("locate", "Locate code", StepRequirement.LOCATE)
    ledger.add_step("fix", "Fix and verify", StepRequirement.FIX)
    ledger.add_step("untouched", "Run additional tests", StepRequirement.TEST)

    ledger.record(
        action("read-1", "read_file"),
        observation("read-1", metadata={"path": "app.py"}),
        step_ids=("locate",),
    )
    ledger.record(
        action("patch-1", "apply_patch"),
        observation(
            "patch-1",
            metadata={
                "path": "app.py",
                "before_sha256": "a" * 64,
                "after_sha256": "b" * 64,
            },
        ),
        step_ids=("fix",),
    )

    report = ledger.report()
    rendered = report.render()

    assert tuple(step.id for step in report.completed) == ("locate",)
    assert tuple(step.id for step in report.insufficiently_verified) == ("fix",)
    assert tuple(step.id for step in report.incomplete) == ("untouched",)
    assert "Completed steps" in rendered
    assert "Insufficiently verified steps" in rendered
    assert "Incomplete steps" in rendered


def test_recording_same_source_is_idempotent() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("locate", "Locate code", StepRequirement.LOCATE)
    request = action("read-1", "read_file")
    result = observation("read-1", metadata={"path": "app.py"})

    first = ledger.record(request, result, step_ids=("locate",))
    second = ledger.record(request, result, step_ids=("locate",))

    assert first == second
    assert len(ledger.evidence) == 1
    assert len(ledger.get_step("locate").evidence_ids) == 1


def test_fix_requires_successful_verification_after_latest_diff() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("fix", "Fix and verify", StepRequirement.FIX)

    ledger.record(
        action("test-before", "run_command"),
        observation("test-before", metadata={"argv": ["pytest"], "exit_code": 0}),
        step_ids=("fix",),
        verification=True,
    )
    ledger.record(
        action("patch-1", "apply_patch"),
        observation(
            "patch-1",
            metadata={
                "before_sha256": "a" * 64,
                "after_sha256": "b" * 64,
            },
        ),
        step_ids=("fix",),
    )

    assert ledger.get_step("fix").status is StepStatus.PENDING

    ledger.record(
        action("test-after", "run_command"),
        observation("test-after", metadata={"argv": ["pytest"], "exit_code": 0}),
        step_ids=("fix",),
        verification=True,
    )
    assert ledger.get_step("fix").status is StepStatus.PASSED

    ledger.record(
        action("patch-2", "apply_patch"),
        observation(
            "patch-2",
            metadata={
                "before_sha256": "b" * 64,
                "after_sha256": "c" * 64,
            },
        ),
        step_ids=("fix",),
    )
    assert ledger.get_step("fix").status is StepStatus.RUNNING


def test_latest_failed_verification_invalidates_older_success() -> None:
    ledger = EvidenceLedger()
    ledger.add_step("test", "Run tests", StepRequirement.TEST)

    ledger.record(
        action("test-ok", "run_command"),
        observation("test-ok", metadata={"argv": ["pytest"], "exit_code": 0}),
        step_ids=("test",),
        verification=True,
    )
    assert ledger.get_step("test").status is StepStatus.PASSED

    ledger.record(
        action("test-failed", "run_command"),
        observation(
            "test-failed",
            status=ObservationStatus.ERROR,
            metadata={"argv": ["pytest"], "exit_code": 1},
        ),
        step_ids=("test",),
        verification=True,
    )

    assert ledger.get_step("test").status is StepStatus.RUNNING
