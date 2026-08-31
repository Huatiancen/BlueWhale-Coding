"""Repair provider message histories after interruption without replaying side effects."""

from __future__ import annotations

import json
from collections.abc import Sequence

from bluewhale_agent.domain.models import Action, Message, MessageRole

_RETRY_SAFE_TOOLS = {"list_files", "read_file", "search_text", "get_diff"}


def repair_tool_history(messages: Sequence[Message]) -> list[Message]:
    """Pair pending calls and remove orphan tool results while preserving order."""

    repaired: list[Message] = []
    pending: dict[str, Action] = {}

    def flush_pending() -> None:
        for action in pending.values():
            retry_safe = action.tool_name in _RETRY_SAFE_TOOLS
            repaired.append(
                Message(
                    role=MessageRole.TOOL,
                    content=json.dumps(
                        {
                            "status": "interrupted",
                            "summary": (
                                "Tool execution was interrupted before a result was recorded."
                            ),
                            "retry_safe": retry_safe,
                        },
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                    tool_call_id=action.id,
                )
            )
        pending.clear()

    for message in messages:
        if message.role is MessageRole.ASSISTANT and message.tool_calls:
            flush_pending()
            repaired.append(message)
            pending = {action.id: action for action in message.tool_calls}
            continue
        if message.role is MessageRole.TOOL:
            tool_call_id = message.tool_call_id
            if tool_call_id is not None and tool_call_id in pending:
                repaired.append(message)
                del pending[tool_call_id]
            continue
        flush_pending()
        repaired.append(message)
    flush_pending()
    return repaired
