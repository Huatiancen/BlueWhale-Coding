"""Parsing for deterministic `/skill:name` user invocations."""

from __future__ import annotations

import re
from dataclasses import dataclass

_COMMAND = re.compile(
    r"^/skill:(?P<name>(?!-)(?!.*--)[a-z0-9-]{1,64}(?<!-))(?:\s+(?P<arguments>.*))?$",
    re.DOTALL,
)


class SkillInvocationError(ValueError):
    """The user attempted an explicit Skill command with invalid syntax."""


@dataclass(frozen=True)
class SkillInvocation:
    name: str
    arguments: str


def parse_skill_invocation(task: str) -> SkillInvocation | None:
    stripped = task.strip()
    if not stripped.startswith("/skill:"):
        return None
    matched = _COMMAND.fullmatch(stripped)
    if matched is None:
        raise SkillInvocationError("Invalid Skill command; use /skill:<name> [arguments]")
    return SkillInvocation(
        name=matched.group("name"),
        arguments=(matched.group("arguments") or "").strip(),
    )
