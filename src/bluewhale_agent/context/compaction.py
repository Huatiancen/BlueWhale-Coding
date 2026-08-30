"""Deterministic structured summaries for older conversation turns."""

from __future__ import annotations

import json
from collections.abc import Sequence

from bluewhale_agent.domain.models import Message, MessageRole


def summarize_conversation(messages: Sequence[Message], *, max_chars: int = 6_000) -> str:
    """Retain goals, decisions, touched paths and outcomes without model inference."""

    goals: list[str] = []
    decisions: list[str] = []
    actions: list[str] = []
    outcomes: list[str] = []
    for message in messages:
        content = " ".join((message.content or "").split())
        if message.role is MessageRole.USER and content:
            goals.append(content)
        elif message.role is MessageRole.ASSISTANT:
            if content:
                decisions.append(content)
            for action in message.tool_calls:
                target = (
                    action.arguments.get("path")
                    or action.arguments.get("command")
                    or action.arguments.get("pattern")
                    or ""
                )
                actions.append(f"{action.tool_name}: {target}".rstrip())
        elif message.role is MessageRole.TOOL and content:
            try:
                payload = json.loads(content)
            except (json.JSONDecodeError, TypeError):
                outcomes.append(content)
            else:
                status = (
                    payload.get("status", "unknown")
                    if isinstance(payload, dict)
                    else "unknown"
                )
                summary = payload.get("summary", "") if isinstance(payload, dict) else ""
                outcomes.append(f"{status}: {summary}".rstrip())

    sections = [
        ("Goals", goals),
        ("Decisions", decisions),
        ("Tool actions and changed targets", actions),
        ("Observed outcomes", outcomes),
    ]
    lines = ["# Structured conversation summary"]
    for title, values in sections:
        if not values:
            continue
        lines.append(f"\n## {title}")
        lines.extend(f"- {value}" for value in values[-12:])
    result = "\n".join(lines)
    if len(result) <= max_chars:
        return result
    marker = "\n...[older summary truncated]...\n"
    return result[: max_chars - len(marker)] + marker
