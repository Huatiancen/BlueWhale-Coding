from collections.abc import Awaitable, Callable
from pathlib import Path
from types import SimpleNamespace

import pytest
from openai import APIConnectionError, APIStatusError
from pydantic import SecretStr

from bluewhale_agent.config import Settings
from bluewhale_agent.domain.models import Limits, Message, MessageRole
from bluewhale_agent.providers.base import ModelProtocolError, ProviderRequestError
from bluewhale_agent.providers.deepseek import DeepSeekProvider


class FakeCompletions:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.requests: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.requests.append(kwargs)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome


class FakeStream:
    def __init__(self, chunks: list[object]) -> None:
        self._chunks = chunks

    def __aiter__(self):
        self._iterator = iter(self._chunks)
        return self

    async def __anext__(self) -> object:
        try:
            return next(self._iterator)
        except StopIteration as error:
            raise StopAsyncIteration from error


class FakeClient:
    def __init__(self, outcomes: list[object]) -> None:
        self.completions = FakeCompletions(outcomes)
        self.chat = SimpleNamespace(completions=self.completions)


class FakeStatusError(APIStatusError):
    def __init__(self, status_code: int) -> None:
        Exception.__init__(self, f"HTTP {status_code}")
        self.status_code = status_code


class FakeConnectionError(APIConnectionError):
    def __init__(self) -> None:
        Exception.__init__(self, "connection failed")


def response(
    *,
    content: str | None = "done",
    finish_reason: str = "stop",
    reasoning_content: str | None = None,
    tool_calls: list[object] | None = None,
) -> object:
    message = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls or [],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(finish_reason=finish_reason, message=message)]
    )


def tool_call(call_id: str, name: str, arguments: str) -> object:
    return SimpleNamespace(
        id=call_id,
        type="function",
        function=SimpleNamespace(name=name, arguments=arguments),
    )


def stream_chunk(
    *,
    content: str | None = None,
    reasoning_content: str | None = None,
    finish_reason: str | None = None,
    tool_calls: list[object] | None = None,
) -> object:
    delta = SimpleNamespace(
        content=content,
        reasoning_content=reasoning_content,
        tool_calls=tool_calls or [],
    )
    return SimpleNamespace(
        choices=[SimpleNamespace(delta=delta, finish_reason=finish_reason)]
    )


def settings(*, max_api_retries: int = 2) -> Settings:
    return Settings.model_construct(
        deepseek_api_key=SecretStr("test-key"),
        model="test-model",
        base_url="https://api.deepseek.com",
        workspace=Path.cwd(),
        limits=Limits(max_api_retries=max_api_retries),
    )


def provider(
    outcomes: list[object],
    *,
    max_api_retries: int = 2,
    sleep: Callable[[float], Awaitable[None]] | None = None,
) -> tuple[DeepSeekProvider, FakeClient]:
    client = FakeClient(outcomes)
    instance = DeepSeekProvider(
        settings(max_api_retries=max_api_retries),
        client=client,
        sleep=sleep,
    )
    return instance, client


@pytest.mark.asyncio
async def test_complete_converts_plain_text_response() -> None:
    instance, client = provider([response(content="finished")])

    result = await instance.complete(
        [Message(role=MessageRole.USER, content="fix the bug")],
        [],
    )

    assert result.content == "finished"
    assert result.finish_reason == "stop"
    assert result.tool_calls == ()
    assert client.completions.requests[0]["model"] == "test-model"
    assert client.completions.requests[0]["messages"] == [
        {"role": "user", "content": "fix the bug"}
    ]


@pytest.mark.asyncio
async def test_stream_emits_reasoning_separately_and_assembles_final_answer() -> None:
    chunks = FakeStream(
        [
            stream_chunk(reasoning_content="先检查"),
            stream_chunk(content="修复"),
            stream_chunk(content="完成", finish_reason="stop"),
        ]
    )
    instance, client = provider([chunks])
    deltas = []

    result = await instance.stream([], [], deltas.append)

    assert [(delta.kind, delta.content) for delta in deltas] == [
        ("reasoning", "先检查"),
        ("answer", "修复"),
        ("answer", "完成"),
    ]
    assert result.reasoning_content == "先检查"
    assert result.content == "修复完成"
    assert client.completions.requests[0]["stream"] is True


@pytest.mark.asyncio
async def test_complete_preserves_reasoning_and_multiple_tool_calls() -> None:
    instance, _ = provider(
        [
            response(
                content=None,
                finish_reason="tool_calls",
                reasoning_content="inspect both files",
                tool_calls=[
                    tool_call("call_1", "read_file", '{"path":"a.py"}'),
                    tool_call("call_2", "read_file", '{"path":"b.py"}'),
                ],
            )
        ]
    )

    result = await instance.complete([], [{"type": "function"}])

    assert result.reasoning_content == "inspect both files"
    assert [action.id for action in result.tool_calls] == ["call_1", "call_2"]
    assert result.tool_calls[1].arguments == {"path": "b.py"}


@pytest.mark.asyncio
async def test_complete_rejects_invalid_tool_arguments_json() -> None:
    instance, _ = provider(
        [response(finish_reason="tool_calls", tool_calls=[tool_call("call_1", "read", "{")])]
    )

    with pytest.raises(ModelProtocolError, match="call_1.*valid JSON"):
        await instance.complete([], [])


@pytest.mark.asyncio
async def test_complete_rejects_non_object_tool_arguments() -> None:
    instance, _ = provider(
        [response(finish_reason="tool_calls", tool_calls=[tool_call("call_1", "read", "[]")])]
    )

    with pytest.raises(ModelProtocolError, match="JSON object"):
        await instance.complete([], [])


@pytest.mark.asyncio
async def test_complete_wraps_invalid_action_fields_as_protocol_error() -> None:
    instance, _ = provider(
        [
            response(
                finish_reason="tool_calls",
                tool_calls=[tool_call("call_1", "invalid tool name", "{}")],
            )
        ]
    )

    with pytest.raises(ModelProtocolError, match="call_1.*invalid fields"):
        await instance.complete([], [])


@pytest.mark.asyncio
async def test_complete_rejects_unknown_finish_reason() -> None:
    instance, _ = provider([response(finish_reason="mystery")])

    with pytest.raises(ModelProtocolError, match="mystery"):
        await instance.complete([], [])


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [429, 500, 503])
async def test_complete_retries_transient_status_errors(status_code: int) -> None:
    delays: list[float] = []

    async def record_sleep(delay: float) -> None:
        delays.append(delay)

    instance, client = provider(
        [FakeStatusError(status_code), response(content="recovered")],
        sleep=record_sleep,
    )

    result = await instance.complete([], [])

    assert result.content == "recovered"
    assert len(client.completions.requests) == 2
    assert delays == [1.0]


@pytest.mark.asyncio
async def test_complete_retries_connection_errors() -> None:
    async def no_wait(_: float) -> None:
        return None

    instance, client = provider(
        [FakeConnectionError(), response(content="recovered")],
        sleep=no_wait,
    )

    result = await instance.complete([], [])

    assert result.content == "recovered"
    assert len(client.completions.requests) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("status_code", [401, 402])
async def test_complete_does_not_retry_authentication_or_balance_errors(
    status_code: int,
) -> None:
    instance, client = provider([FakeStatusError(status_code)])

    with pytest.raises(ProviderRequestError, match=str(status_code)):
        await instance.complete([], [])

    assert len(client.completions.requests) == 1


@pytest.mark.asyncio
async def test_complete_stops_after_retry_limit() -> None:
    async def no_wait(_: float) -> None:
        return None

    instance, client = provider(
        [FakeStatusError(503), FakeStatusError(503), FakeStatusError(503)],
        max_api_retries=2,
        sleep=no_wait,
    )

    with pytest.raises(ProviderRequestError, match="3 attempts"):
        await instance.complete([], [])

    assert len(client.completions.requests) == 3


@pytest.mark.asyncio
async def test_complete_never_sends_credentials_in_request_body() -> None:
    instance, client = provider([response()])

    await instance.complete([], [])

    request_body = repr(client.completions.requests[0])
    assert "test-key" not in request_body
    assert "Authorization" not in request_body


def test_provider_requires_api_key_when_building_real_client() -> None:
    missing_key = settings().model_copy(update={"deepseek_api_key": None})

    with pytest.raises(ValueError, match="DEEPSEEK_API_KEY"):
        DeepSeekProvider(missing_key)


def test_provider_builds_real_client_when_socks_proxy_is_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ALL_PROXY", "socks5h://127.0.0.1:1080")
    monkeypatch.setenv("all_proxy", "socks5h://127.0.0.1:1080")

    instance = DeepSeekProvider(settings())

    assert instance is not None
