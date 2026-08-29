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


def test_parse_builds_a_pipeline_inside_one_conditional_step() -> None:
    plan = parse_command_plan("printf 'hello\\n' | tr a-z A-Z && wc -c")

    assert plan.steps[0].commands == (
        ("printf", "hello\\n"),
        ("tr", "a-z", "A-Z"),
    )
    assert plan.steps[0].condition is StepCondition.ALWAYS
    assert plan.steps[1].commands == (("wc", "-c"),)
    assert plan.steps[1].condition is StepCondition.ON_SUCCESS


@pytest.mark.parametrize(
    "command",
    [
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


@pytest.mark.parametrize("command", ["| echo ok", "echo ok |", "echo | | wc"])
def test_parse_rejects_incomplete_pipeline(command: str) -> None:
    with pytest.raises(CommandPlanError, match="命令|管道"):
        parse_command_plan(command)


def test_shell_metacharacters_inside_quotes_remain_arguments() -> None:
    plan = parse_command_plan("printf '%s' 'a && b | c > d'")

    assert plan.steps[0].argv == ("printf", "%s", "a && b | c > d")
