"""Provider-neutral model interface and errors."""

from __future__ import annotations

from typing import Protocol

from bluewhale_agent.domain.models import Message, ModelResponse


class ModelProtocolError(RuntimeError):
    """Raised when a provider response violates the expected protocol."""


class ProviderRequestError(RuntimeError):
    """Raised when a provider request cannot complete within its retry policy."""

    def __init__(self, message: str, *, status_code: int | None, attempts: int) -> None:
        super().__init__(message)
        self.status_code = status_code
        self.attempts = attempts


class ModelProvider(Protocol):
    """Interface consumed by the future agent loop."""

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, object]],
    ) -> ModelResponse:
        """Return one provider-neutral model response."""
        ...

