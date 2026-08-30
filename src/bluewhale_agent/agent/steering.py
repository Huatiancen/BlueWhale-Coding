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
