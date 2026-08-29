from __future__ import annotations

import pytest

from bluewhale_agent.runtime.command_plan import (
    CommandPlanError,
    StepCondition,
    parse_command_plan,
)


def test_parse_preserves_quotes_and_conditions() -> None:
    plan = parse_command_plan("printf 'a b' && false || echo fallback; pwd")

    assert [(step.argv, step.condition) for step in plan.steps] == [
        (("printf", "a b"), StepCondition.ALWAYS),
        (("false",), StepCondition.ON_SUCCESS),
        (("echo", "fallback"), StepCondition.ON_FAILURE),
        (("pwd",), StepCondition.ALWAYS),
    ]


@pytest.mark.parametrize(
    "command",
    [
        "echo ok | wc",
        "echo x > out.txt",
        "cat < input.txt",
        "sleep 1 &",
        "echo $(pwd)",
        "echo `pwd`",
        "echo *.py",
        "NAME=value command",
    ],
)
def test_parse_rejects_unsupported_shell_syntax(command: str) -> None:
    with pytest.raises(CommandPlanError, match="暂不支持"):
        parse_command_plan(command)


@pytest.mark.parametrize(
    "command",
    ["", "   ", "echo ok &&", "echo ok ||", "; echo ok", "echo one && || echo two"],
)
def test_parse_rejects_incomplete_command(command: str) -> None:
    with pytest.raises(CommandPlanError, match="命令"):
        parse_command_plan(command)


def test_shell_metacharacters_inside_quotes_remain_arguments() -> None:
    plan = parse_command_plan("printf '%s' 'a && b | c > d'")

    assert plan.steps[0].argv == ("printf", "%s", "a && b | c > d")
