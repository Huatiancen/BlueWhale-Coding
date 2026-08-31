from __future__ import annotations

import json

from bluewhale_agent.domain.models import Action, Message, MessageRole
from bluewhale_agent.providers.recovery import repair_tool_history


def test_repair_tool_history_pairs_interrupted_calls_before_next_message() -> None:
    calls = (
        Action(id="read-1", tool_name="read_file", arguments={"path": "a.py"}),
        Action(id="write-1", tool_name="write_file", arguments={"path": "a.py"}),
    )
    history = [
        Message(role=MessageRole.ASSISTANT, content=None, tool_calls=calls),
        Message(
            role=MessageRole.TOOL,
            content='{"status":"success"}',
            tool_call_id="read-1",
        ),
        Message(role=MessageRole.USER, content="继续"),
    ]

    repaired = repair_tool_history(history)

    assert [message.role for message in repaired] == [
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.TOOL,
        MessageRole.USER,
    ]
    inserted = repaired[2]
    assert inserted.tool_call_id == "write-1"
    payload = json.loads(inserted.content or "{}")
    assert payload["status"] == "interrupted"
    assert payload["retry_safe"] is False


def test_repair_tool_history_drops_orphan_tool_results() -> None:
    history = [
        Message(
            role=MessageRole.TOOL,
            content='{"status":"success"}',
            tool_call_id="missing-call",
        ),
        Message(role=MessageRole.USER, content="continue"),
    ]

    assert repair_tool_history(history) == [
        Message(role=MessageRole.USER, content="continue")
    ]


def test_repair_tool_history_is_idempotent() -> None:
    history = [
        Message(
            role=MessageRole.ASSISTANT,
            content=None,
            tool_calls=(Action(id="read-1", tool_name="read_file"),),
        )
    ]

    once = repair_tool_history(history)
    assert repair_tool_history(once) == once
