from bluewhale_agent.context.compaction import summarize_conversation
from bluewhale_agent.domain.models import Action, Message, MessageRole


def test_structured_summary_preserves_goals_changes_and_tool_decisions() -> None:
    messages = [
        Message(role=MessageRole.USER, content="修复登录错误"),
        Message(
            role=MessageRole.ASSISTANT,
            content="先定位鉴权逻辑",
            tool_calls=(
                Action(
                    id="call-1",
                    tool_name="apply_patch",
                    arguments={"path": "src/auth.py", "patch": "..."},
                ),
            ),
        ),
        Message(role=MessageRole.TOOL, content='{"status":"success"}', tool_call_id="call-1"),
    ]

    summary = summarize_conversation(messages)

    assert "修复登录错误" in summary
    assert "src/auth.py" in summary
    assert "apply_patch" in summary
    assert "success" in summary
