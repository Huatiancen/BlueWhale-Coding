"""Append-only JSONL storage for replayable run events."""

from __future__ import annotations

import os
import re
from datetime import UTC, datetime
from pathlib import Path
from threading import Lock

from pydantic import BaseModel, ConfigDict, Field, ValidationError

from bluewhale_agent.domain.events import RunEvent
from bluewhale_agent.trajectory.redaction import redact

_RUN_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_-]{0,127}$")


class TrajectoryCorruptionError(RuntimeError):
    """Raised when corruption is found before the final JSONL record."""


class StoredEvent(BaseModel):
    """A run event enriched with durable ordering metadata."""

    model_config = ConfigDict(frozen=True)

    sequence: int = Field(ge=1)
    recorded_at: datetime
    schema_version: int = Field(default=1, ge=1)
    event: RunEvent


class TrajectoryStore:
    """Persist and replay one run's events as newline-delimited JSON."""

    def __init__(
        self,
        workspace: Path,
        run_id: str,
        *,
        runs_root: Path | None = None,
    ) -> None:
        if _RUN_ID.fullmatch(run_id) is None:
            raise ValueError(f"Invalid run id: {run_id!r}")

        self.run_id = run_id
        selected_root = runs_root or workspace.resolve() / ".bluewhale" / "runs"
        self.run_dir = selected_root.resolve(strict=False) / run_id
        self.events_path = self.run_dir / "events.jsonl"
        self._lock = Lock()
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.events_path.touch(exist_ok=True)
        self._sequence = self._recover_and_find_sequence()

    def append(self, event: RunEvent) -> StoredEvent:
        """Redact and durably append one event with a monotonic sequence."""
        if event.run_id != self.run_id:
            raise ValueError(
                f"Event run id {event.run_id!r} does not match store {self.run_id!r}."
            )

        with self._lock:
            event_data = redact(event.model_dump(mode="json"))
            sanitized_event = RunEvent.model_validate(event_data)
            stored = StoredEvent(
                sequence=self._sequence + 1,
                recorded_at=datetime.now(UTC),
                event=sanitized_event,
            )
            with self.events_path.open("a", encoding="utf-8") as stream:
                stream.write(stored.model_dump_json())
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            self._sequence = stored.sequence
            return stored

    def events_after(self, sequence: int) -> list[StoredEvent]:
        """Read events whose sequence is greater than the supplied cursor."""
        if sequence < 0:
            raise ValueError("Sequence cursor cannot be negative.")

        with self._lock:
            events = self._read_events()
        return [event for event in events if event.sequence > sequence]

    def _recover_and_find_sequence(self) -> int:
        data = self.events_path.read_bytes()
        if not data:
            return 0

        lines = data.splitlines(keepends=True)
        offset = 0
        events: list[StoredEvent] = []
        for index, line in enumerate(lines):
            try:
                event = StoredEvent.model_validate_json(line)
            except (ValidationError, ValueError):
                if index != len(lines) - 1:
                    raise TrajectoryCorruptionError(
                        f"Invalid trajectory record at line {index + 1}."
                    ) from None
                with self.events_path.open("r+b") as stream:
                    stream.truncate(offset)
                break
            events.append(event)
            offset += len(line)

        self._validate_sequences(events)
        return events[-1].sequence if events else 0

    def _read_events(self) -> list[StoredEvent]:
        events: list[StoredEvent] = []
        with self.events_path.open("r", encoding="utf-8") as stream:
            for line_number, line in enumerate(stream, start=1):
                if not line.strip():
                    continue
                try:
                    events.append(StoredEvent.model_validate_json(line))
                except (ValidationError, ValueError) as error:
                    raise TrajectoryCorruptionError(
                        f"Invalid trajectory record at line {line_number}."
                    ) from error
        self._validate_sequences(events)
        return events

    @staticmethod
    def _validate_sequences(events: list[StoredEvent]) -> None:
        for expected, event in enumerate(events, start=1):
            if event.sequence != expected:
                raise TrajectoryCorruptionError(
                    f"Expected trajectory sequence {expected}, found {event.sequence}."
                )
