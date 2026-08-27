"""Deterministic test doubles shared by integration tests."""

from __future__ import annotations

from collections.abc import Iterable

from bluewhale_agent.domain.models import Message, ModelResponse


class FakeModelProvider:
    """Replay provider responses without making network requests."""

    def __init__(self, responses: Iterable[ModelResponse | Exception]) -> None:
        self._responses = iter(responses)
        self.calls: list[tuple[list[Message], list[dict[str, object]]]] = []

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, object]],
    ) -> ModelResponse:
        self.calls.append((list(messages), list(tools)))
        try:
            response = next(self._responses)
        except StopIteration as exc:
            raise AssertionError("FakeModelProvider has no response left") from exc
        if isinstance(response, Exception):
            raise response
        return response
