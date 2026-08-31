from __future__ import annotations

import pytest

from bluewhale_agent.skills.invocation import SkillInvocationError, parse_skill_invocation


def test_parses_explicit_skill_and_keeps_arguments_separate() -> None:
    invocation = parse_skill_invocation("/skill:python-testing run unit tests")

    assert invocation is not None
    assert invocation.name == "python-testing"
    assert invocation.arguments == "run unit tests"


def test_returns_none_for_normal_user_message() -> None:
    assert parse_skill_invocation("please run python tests") is None


@pytest.mark.parametrize(
    "task",
    ["/skill:", "/skill:BadName test", "/skill:two--dash", "/skill:-leading"],
)
def test_rejects_malformed_explicit_skill_commands(task: str) -> None:
    with pytest.raises(SkillInvocationError, match="Invalid Skill command"):
        parse_skill_invocation(task)
