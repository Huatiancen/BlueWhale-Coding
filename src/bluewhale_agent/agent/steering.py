"""In-memory user instructions delivered at safe Agent Loop boundaries."""

from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


class RuntimeInstruction(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    content: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class RuntimeInstructionQueue:
    """Single-event-loop FIFO with withdrawal before delivery."""

    def __init__(self) -> None:
        self._pending: list[RuntimeInstruction] = []

    @property
    def pending(self) -> tuple[RuntimeInstruction, ...]:
        return tuple(self._pending)

    def enqueue(self, content: str) -> RuntimeInstruction:
        item = RuntimeInstruction(content=content.strip())
        self._pending.append(item)
        return item

    def withdraw(self, instruction_id: str) -> RuntimeInstruction | None:
        for index, item in enumerate(self._pending):
            if item.id == instruction_id:
                return self._pending.pop(index)
        return None

    def drain(self) -> tuple[RuntimeInstruction, ...]:
        items = tuple(self._pending)
        self._pending.clear()
        return items


class QueuedFollowUp(BaseModel):
    """A later user turn waiting behind the currently running turn."""

    model_config = ConfigDict(frozen=True)

    id: str = Field(default_factory=lambda: uuid4().hex)
    content: str = Field(min_length=1)
    created_at: datetime = Field(default_factory=lambda: datetime.now(UTC))


class QueuedFollowUpQueue:
    """Single-event-loop FIFO for user turns scheduled after the active turn."""

    def __init__(self) -> None:
        self._pending: list[QueuedFollowUp] = []

    @property
    def pending(self) -> tuple[QueuedFollowUp, ...]:
        return tuple(self._pending)

    def enqueue(self, content: str) -> QueuedFollowUp:
        item = QueuedFollowUp(content=content.strip())
        self._pending.append(item)
        return item

    def withdraw(self, follow_up_id: str) -> QueuedFollowUp | None:
        for index, item in enumerate(self._pending):
            if item.id == follow_up_id:
                return self._pending.pop(index)
        return None

    def take_for_steering(self, follow_up_id: str) -> QueuedFollowUp | None:
        return self.withdraw(follow_up_id)

    def pop_next(self) -> QueuedFollowUp | None:
        if not self._pending:
            return None
        return self._pending.pop(0)

    def drain(self) -> tuple[QueuedFollowUp, ...]:
        items = tuple(self._pending)
        self._pending.clear()
        return items
