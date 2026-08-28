from __future__ import annotations

import os

import pytest

from bluewhale_agent.config import Settings
from bluewhale_agent.domain.models import Message, MessageRole
from bluewhale_agent.providers.deepseek import DeepSeekProvider

LIVE_TESTS_ENABLED = os.getenv("BLUEWHALE_RUN_LIVE_TESTS") == "1" and bool(
    os.getenv("DEEPSEEK_API_KEY")
)
LIVE_TEST_REASON = (
    "set BLUEWHALE_RUN_LIVE_TESTS=1 and DEEPSEEK_API_KEY to run billed DeepSeek tests"
)

pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not LIVE_TESTS_ENABLED, reason=LIVE_TEST_REASON),
]


def lookup_tool() -> dict[str, object]:
    return {
        "type": "function",
        "function": {
            "name": "lookup_temperature",
            "description": "Return the current temperature for one city.",
            "parameters": {
                "type": "object",
                "properties": {"city": {"type": "string"}},
                "required": ["city"],
                "additionalProperties": False,
            },
        },
    }


def live_provider() -> DeepSeekProvider:
    return DeepSeekProvider(Settings())


async def test_live_plain_answer_contract() -> None:
    result = await live_provider().complete(
        [Message(role=MessageRole.USER, content="Reply with exactly: BLUEWHALE_OK")],
        [],
    )

    assert result.content is not None
    assert "BLUEWHALE_OK" in result.content
    assert result.finish_reason == "stop"
    assert result.tool_calls == ()


async def test_live_tool_call_contract() -> None:
    result = await live_provider().complete(
        [
            Message(
                role=MessageRole.USER,
                content=(
                    "You must call lookup_temperature for Hangzhou. Do not answer from memory."
                ),
            )
        ],
        [lookup_tool()],
    )

    assert result.finish_reason == "tool_calls"
    assert len(result.tool_calls) == 1
    assert result.tool_calls[0].tool_name == "lookup_temperature"
    assert result.tool_calls[0].arguments.get("city")


async def test_live_thinking_tool_history_contract() -> None:
    provider = live_provider()
    user = Message(
        role=MessageRole.USER,
        content=(
            "Call lookup_temperature for Hangzhou before answering. "
            "After the tool result, report the temperature in one sentence."
        ),
    )
    first = await provider.complete([user], [lookup_tool()])

    assert first.tool_calls
    assert first.reasoning_content
    tool_call = first.tool_calls[0]
    second = await provider.complete(
        [
            user,
            Message(
                role=MessageRole.ASSISTANT,
                content=first.content,
                reasoning_content=first.reasoning_content,
                tool_calls=first.tool_calls,
            ),
            Message(
                role=MessageRole.TOOL,
                content='{"city":"Hangzhou","temperature_c":24}',
                tool_call_id=tool_call.id,
            ),
        ],
        [lookup_tool()],
    )

    assert second.content is not None
    assert "24" in second.content
    assert second.finish_reason == "stop"
