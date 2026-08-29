"""Parse a conservative subset of shell sequencing into direct process steps."""

from __future__ import annotations

import re
import shlex
from dataclasses import dataclass
from enum import StrEnum


class CommandPlanError(ValueError):
    """Raised when a command is incomplete or requires unsupported shell behavior."""


class StepCondition(StrEnum):
    """Condition under which a command step should run."""

    ALWAYS = "always"
    ON_SUCCESS = "on_success"
    ON_FAILURE = "on_failure"


@dataclass(frozen=True)
class CommandStep:
    """One process pipeline and its dependency on the previous executed step."""

    commands: tuple[tuple[str, ...], ...]
    condition: StepCondition

    @property
    def argv(self) -> tuple[str, ...]:
        """Return the command whose exit status represents this pipeline."""

        return self.commands[-1]


@dataclass(frozen=True)
class CommandPlan:
    """A validated sequence of direct, non-shell process invocations."""

    steps: tuple[CommandStep, ...]


_CONDITIONS = {
    ";": StepCondition.ALWAYS,
    "&&": StepCondition.ON_SUCCESS,
    "||": StepCondition.ON_FAILURE,
}
_PUNCTUATION = "|&;<>"
_ASSIGNMENT = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*=")


def parse_command_plan(command: str) -> CommandPlan:
    """Parse direct pipelines joined by ``;``, ``&&`` or ``||``."""

    if not command.strip():
        raise CommandPlanError("命令不能为空")
    _reject_unquoted_expansions(command)
    lexer = shlex.shlex(command, posix=True, punctuation_chars=_PUNCTUATION)
    lexer.whitespace_split = True
    lexer.commenters = ""
    try:
        tokens = list(lexer)
    except ValueError as exc:
        raise CommandPlanError(f"命令无法解析：{exc}") from exc

    steps: list[CommandStep] = []
    pipeline: list[tuple[str, ...]] = []
    current: list[str] = []
    condition = StepCondition.ALWAYS
    for token in tokens:
        if token == "|":
            if not current:
                raise CommandPlanError("管道符前缺少命令")
            pipeline.append(tuple(current))
            current = []
            continue
        if token in _CONDITIONS:
            if not current:
                raise CommandPlanError("命令连接符前缺少命令")
            pipeline.append(tuple(current))
            steps.append(CommandStep(commands=tuple(pipeline), condition=condition))
            pipeline = []
            current = []
            condition = _CONDITIONS[token]
            continue
        if token and all(character in _PUNCTUATION for character in token):
            raise CommandPlanError(f"暂不支持 Shell 结构：{token}")
        if not current and _ASSIGNMENT.match(token):
            raise CommandPlanError("暂不支持命令前的环境变量赋值")
        current.append(token)

    if not current:
        raise CommandPlanError("命令不能以连接符结尾")
    pipeline.append(tuple(current))
    steps.append(CommandStep(commands=tuple(pipeline), condition=condition))
    return CommandPlan(steps=tuple(steps))


def _reject_unquoted_expansions(command: str) -> None:
    quote: str | None = None
    escaped = False
    index = 0
    while index < len(command):
        character = command[index]
        if escaped:
            escaped = False
            index += 1
            continue
        if character == "\\" and quote != "'":
            escaped = True
            index += 1
            continue
        if quote is not None:
            if character == quote:
                quote = None
            index += 1
            continue
        if character in {"'", '"'}:
            quote = character
        elif character == "`":
            raise CommandPlanError("暂不支持反引号命令替换")
        elif character == "$":
            raise CommandPlanError("暂不支持 Shell 变量或命令替换")
        elif character in {"(", ")"}:
            raise CommandPlanError("暂不支持子 Shell")
        elif character in {"*", "?", "["}:
            raise CommandPlanError("暂不支持 Shell 通配符展开")
        index += 1
