from __future__ import annotations

from pathlib import Path

from bluewhale_agent.agent.checkpoints import (
    CheckpointPhase,
    RunCheckpoint,
    RunCheckpointStore,
)
from bluewhale_agent.domain.models import Action, Message, MessageRole
from bluewhale_agent.providers.recovery import repair_tool_history


def test_checkpoint_round_trip_and_reconciliation_state(tmp_path: Path) -> None:
    store = RunCheckpointStore(tmp_path, "recoverable-run")
    pending = Action(id="write-1", tool_name="write_file", arguments={"path": "app.py"})

    saved = store.save(
        RunCheckpoint(
            run_id="recoverable-run",
            phase=CheckpointPhase.TOOL_EXECUTING,
            messages=(Message(role=MessageRole.USER, content="fix it"),),
            pending_action=pending,
            completed_action_ids=("read-1",),
            changeset_id="turn-1",
        )
    )

    assert saved.needs_reconciliation is True
    loaded = store.load_latest()
    assert loaded == saved
    assert loaded is not None
    assert loaded.pending_action == pending


def test_checkpoint_write_redacts_secrets(tmp_path: Path) -> None:
    store = RunCheckpointStore(tmp_path, "redacted-run")

    store.save(
        RunCheckpoint(
            run_id="redacted-run",
            phase=CheckpointPhase.MODEL_REQUEST,
            messages=(
                Message(
                    role=MessageRole.USER,
                    content="api_key=sk-secret-value authorization=Bearer private-token",
                ),
            ),
        )
    )

    raw = store.path.read_text(encoding="utf-8")
    assert "sk-secret-value" not in raw
    assert "private-token" not in raw
    assert "[REDACTED]" in raw


def test_corrupt_checkpoint_is_quarantined(tmp_path: Path) -> None:
    store = RunCheckpointStore(tmp_path, "corrupt-run")
    store.path.parent.mkdir(parents=True, exist_ok=True)
    store.path.write_text("{not-json", encoding="utf-8")

    assert store.load_latest() is None
    assert not store.path.exists()
    assert (store.path.parent / "checkpoint.corrupt.json").read_text(
        encoding="utf-8"
    ) == "{not-json"


def test_completed_tool_does_not_require_reconciliation(tmp_path: Path) -> None:
    checkpoint = RunCheckpoint(
        run_id="completed-run",
        phase=CheckpointPhase.TOOL_FINISHED,
        completed_action_ids=("write-1",),
    )

    assert checkpoint.needs_reconciliation is False


def test_checkpoint_records_original_task_and_repairs_pending_action() -> None:
    pending = Action(id="write-1", tool_name="write_file", arguments={"path": "app.py"})
    checkpoint = RunCheckpoint(
        run_id="resume-run",
        task="修复 app.py",
        phase=CheckpointPhase.TOOL_EXECUTING,
        messages=(Message(role=MessageRole.ASSISTANT, content=None, tool_calls=(pending,)),),
        pending_action=pending,
    )

    repaired = repair_tool_history(checkpoint.messages)

    assert checkpoint.task == "修复 app.py"
    assert checkpoint.needs_reconciliation is True
    assert repaired[-1].role is MessageRole.TOOL
    assert repaired[-1].tool_call_id == "write-1"
