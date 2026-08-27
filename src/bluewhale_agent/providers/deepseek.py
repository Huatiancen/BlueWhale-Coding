"""DeepSeek Chat Completions adapter using the OpenAI-compatible client."""

from __future__ import annotations

import asyncio
import json
from collections.abc import Awaitable, Callable, Sequence
from typing import Protocol, cast

from openai import (
    APIConnectionError,
    APIStatusError,
    APITimeoutError,
    AsyncOpenAI,
)
from pydantic import ValidationError

from bluewhale_agent.config import Settings
from bluewhale_agent.domain.models import Action, Message, MessageRole, ModelResponse
from bluewhale_agent.providers.base import ModelProtocolError, ProviderRequestError

_ALLOWED_FINISH_REASONS = {
    "stop",
    "length",
    "content_filter",
    "tool_calls",
    "insufficient_system_resource",
}
_RETRYABLE_STATUS_CODES = {429, 500, 503}


class _FunctionCall(Protocol):
    name: str
    arguments: str


class _ToolCall(Protocol):
    id: str
    type: str
    function: _FunctionCall


class _ResponseMessage(Protocol):
    content: str | None
    reasoning_content: str | None
    tool_calls: Sequence[_ToolCall] | None


class _Choice(Protocol):
    finish_reason: str
    message: _ResponseMessage


class _CompletionResponse(Protocol):
    choices: Sequence[_Choice]


class _Completions(Protocol):
    async def create(self, **kwargs: object) -> _CompletionResponse: ...


class _Chat(Protocol):
    completions: _Completions


class _Client(Protocol):
    chat: _Chat


class DeepSeekProvider:
    """Convert between BlueWhale contracts and DeepSeek's API schema."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: _Client | None = None,
        sleep: Callable[[float], Awaitable[None]] | None = None,
    ) -> None:
        self._settings = settings
        self._sleep = sleep or asyncio.sleep
        if client is not None:
            self._client = client
            return

        if settings.deepseek_api_key is None:
            raise ValueError("DEEPSEEK_API_KEY is required to call DeepSeek.")
        self._client = cast(
            _Client,
            AsyncOpenAI(
                api_key=settings.deepseek_api_key.get_secret_value(),
                base_url=settings.base_url,
                max_retries=0,
            ),
        )

    async def complete(
        self,
        messages: list[Message],
        tools: list[dict[str, object]],
    ) -> ModelResponse:
        """Call DeepSeek and immediately convert its response to domain models."""
        request: dict[str, object] = {
            "model": self._settings.model,
            "messages": [self._serialize_message(message) for message in messages],
            "tools": tools or None,
            "stream": False,
            "reasoning_effort": "high",
            "extra_body": {"thinking": {"type": "enabled"}},
        }
        response = await self._request_with_retries(request)
        return self._parse_response(response)

    async def _request_with_retries(
        self,
        request: dict[str, object],
    ) -> _CompletionResponse:
        max_retries = self._settings.limits.max_api_retries
        for attempt in range(max_retries + 1):
            try:
                return await self._client.chat.completions.create(**request)
            except APIStatusError as error:
                if error.status_code not in _RETRYABLE_STATUS_CODES or attempt >= max_retries:
                    raise ProviderRequestError(
                        self._request_error_message(error.status_code, attempt + 1),
                        status_code=error.status_code,
                        attempts=attempt + 1,
                    ) from error
            except (APIConnectionError, APITimeoutError) as error:
                if attempt >= max_retries:
                    raise ProviderRequestError(
                        self._request_error_message(None, attempt + 1),
                        status_code=None,
                        attempts=attempt + 1,
                    ) from error
            await self._sleep(min(2**attempt, 8.0))

        raise AssertionError("Retry loop exited without returning or raising.")

    @staticmethod
    def _request_error_message(status_code: int | None, attempts: int) -> str:
        status = f"HTTP {status_code}" if status_code is not None else "network error"
        return f"DeepSeek request failed with {status} after {attempts} attempts."

    def _parse_response(self, response: _CompletionResponse) -> ModelResponse:
        if not response.choices:
            raise ModelProtocolError("DeepSeek returned no response choices.")

        choice = response.choices[0]
        if choice.finish_reason not in _ALLOWED_FINISH_REASONS:
            raise ModelProtocolError(
                f"DeepSeek returned unknown finish reason {choice.finish_reason!r}."
            )

        tool_calls = tuple(
            self._parse_tool_call(tool_call) for tool_call in choice.message.tool_calls or ()
        )
        return ModelResponse(
            content=choice.message.content,
            reasoning_content=choice.message.reasoning_content,
            tool_calls=tool_calls,
            finish_reason=choice.finish_reason,
        )

    @staticmethod
    def _parse_tool_call(tool_call: _ToolCall) -> Action:
        try:
            arguments = json.loads(tool_call.function.arguments)
        except json.JSONDecodeError as error:
            raise ModelProtocolError(
                f"Tool call {tool_call.id!r} arguments are not valid JSON."
            ) from error
        if not isinstance(arguments, dict):
            raise ModelProtocolError(
                f"Tool call {tool_call.id!r} arguments must be a JSON object."
            )
        try:
            return Action(
                id=tool_call.id,
                tool_name=tool_call.function.name,
                arguments=arguments,
            )
        except ValidationError as error:
            raise ModelProtocolError(
                f"Tool call {tool_call.id!r} contains invalid fields."
            ) from error

    @staticmethod
    def _serialize_message(message: Message) -> dict[str, object]:
        serialized: dict[str, object] = {
            "role": message.role.value,
            "content": message.content,
        }
        if message.role is MessageRole.ASSISTANT:
            if message.reasoning_content is not None:
                serialized["reasoning_content"] = message.reasoning_content
            if message.tool_calls:
                serialized["tool_calls"] = [
                    {
                        "id": action.id,
                        "type": "function",
                        "function": {
                            "name": action.tool_name,
                            "arguments": json.dumps(
                                action.arguments,
                                ensure_ascii=False,
                                separators=(",", ":"),
                            ),
                        },
                    }
                    for action in message.tool_calls
                ]
        if message.role is MessageRole.TOOL:
            if message.tool_call_id is None:
                raise ModelProtocolError("Tool messages require a tool_call_id.")
            serialized["tool_call_id"] = message.tool_call_id
        return serialized
