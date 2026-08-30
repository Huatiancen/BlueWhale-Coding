"""Provider-neutral model interface and errors."""

from __future__ import annotations

from collections.abc import Callable
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

from bluewhale_agent.domain.models import Message, ModelResponse


class ModelProtocolError(RuntimeError):
    """Raised when a provider response violates the expected protocol."""


class ProviderRequestError(RuntimeError):
    """Raised when a provider request cannot complete within its retry policy."""

    def __init__(self, message: str, *, status_code: int | None, attempts: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts


class ModelDelta(BaseModel):
    """One provider-neutral streaming fragment."""

    model_config = ConfigDict(frozen=True)

    kind: Literal["reasoning", "answer", "tool_call"]
    content: str


class ModelProvider(Protocol):
    """Interface consumed by the future agent loop."""

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, object]],
    ) -> ModelResponse:
        """Return one provider-neutral model response."""
        ...

    async def stream(
        self,
        messages: list[Message],
        tools: list[dict[str, object]],
        on_delta: Callable[[ModelDelta], None],
    ) -> ModelResponse:
        """Stream fragments and return the assembled response."""
        ...
