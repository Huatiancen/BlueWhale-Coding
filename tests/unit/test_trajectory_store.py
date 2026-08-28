import json
from pathlib import Path

import pytest

from bluewhale_agent.domain.events import EventKind, RunEvent
from bluewhale_agent.trajectory.redaction import redact
from bluewhale_agent.trajectory.store import TrajectoryStore


def make_event(run_id: str, payload: dict[str, object] | None = None) -> RunEvent:
    return RunEvent(
        run_id=run_id,
        kind=EventKind.STATE_CHANGED,
        payload=payload or {"status": "running"},
    )


def test_append_assigns_monotonic_sequences_and_supports_resume(tmp_path: Path) -> None:
    store = TrajectoryStore(tmp_path, "run-1")

    first = store.append(make_event("run-1"))
    second = store.append(make_event("run-1", {"status": "verifying"}))

    assert (first.sequence, second.sequence) == (1, 2)
    assert [event.sequence for event in store.events_after(0)] == [1, 2]
    assert [event.sequence for event in store.events_after(1)] == [2]
    assert second.recorded_at.tzinfo is not None


def test_append_redacts_credentials_before_writing_jsonl(tmp_path: Path) -> None:
    store = TrajectoryStore(tmp_path, "run-1")
    api_key_name = "_".join(("DEEPSEEK", "API", "KEY"))
    api_key = "-".join(("sk", "super-secret-value"))
    bearer_header = " ".join(("Authorization:", "Bearer", "bearer-secret-value"))
    env_command = "=".join((api_key_name, "plain-secret python app.py"))
    nested_token = " ".join(("prefix", "-".join(("sk", "another-secret-value")), "suffix"))
    store.append(
        make_event(
            "run-1",
            {
                api_key_name: api_key,
                "header": bearer_header,
                "command": env_command,
                "nested": {"token": nested_token},
            },
        )
    )

    raw = store.events_path.read_text(encoding="utf-8")

    assert "super-secret" not in raw
    assert "bearer-secret" not in raw
    assert "plain-secret" not in raw
    assert "another-secret" not in raw
    assert raw.count("[REDACTED]") >= 4


def test_reopen_recovers_from_a_truncated_last_line(tmp_path: Path) -> None:
    store = TrajectoryStore(tmp_path, "run-1")
    store.append(make_event("run-1"))
    with store.events_path.open("ab") as stream:
        stream.write(b'{"sequence": 2, "event":')

    reopened = TrajectoryStore(tmp_path, "run-1")
    recovered = reopened.events_after(0)
    next_event = reopened.append(make_event("run-1", {"status": "recovered"}))

    assert [event.sequence for event in recovered] == [1]
    assert next_event.sequence == 2
    lines = reopened.events_path.read_text(encoding="utf-8").splitlines()
    assert [json.loads(line)["sequence"] for line in lines] == [1, 2]


def test_redact_handles_nested_collections_without_mutating_input() -> None:
    secret_entry = {"SERVICE_API_KEY": "secret-value"}
    original = {
        "items": ["safe", secret_entry],
        "count": 2,
    }

    result = redact(original)

    assert result == {
        "items": ["safe", {"SERVICE_API_KEY": "[REDACTED]"}],
        "count": 2,
    }
    assert secret_entry["SERVICE_API_KEY"] == "secret-value"


def test_store_rejects_run_ids_that_escape_the_runtime_directory(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="run id"):
        TrajectoryStore(tmp_path, "../escape")


def test_append_rejects_an_event_from_another_run(tmp_path: Path) -> None:
    store = TrajectoryStore(tmp_path, "run-1")

    with pytest.raises(ValueError, match="run-2"):
        store.append(make_event("run-2"))
