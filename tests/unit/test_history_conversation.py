from __future__ import annotations

from datetime import UTC, datetime

import pytest

from bluewhale_agent.domain.events import EventKind, RunEvent
from bluewhale_agent.domain.models import MessageRole, ObservationStatus
from bluewhale_agent.history.conversation import (
    ConversationHistoryError,
    restore_conversation,
)
from bluewhale_agent.trajectory.store import StoredEvent


def test_restore_conversation_preserves_multi_turn_tool_protocol() -> None:
    events = [
        stored(1, EventKind.RUN_STARTED, {"task": "检查 calculator.py"}),
        stored(
            2,
            EventKind.MODEL_RESPONSE,
            {
                "content": None,
                "reasoning_content": "需要先读取文件",
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "read-1",
                        "tool_name": "read_file",
                        "arguments": {"path": "calculator.py"},
                    }
                ],
            },
        ),
        stored(
            3,
            EventKind.OBSERVATION_RECEIVED,
            {
                "observation": {
                    "action_id": "read-1",
                    "status": "success",
                    "summary": "已读取 calculator.py",
                    "content": "return 1\n",
                    "metadata": {"path": "calculator.py"},
                    "duration_ms": 3,
                },
                "verification": False,
            },
        ),
        stored(
            4,
            EventKind.MODEL_RESPONSE,
            {
                "content": "当前函数返回 1。",
                "finish_reason": "stop",
                "tool_calls": [],
            },
        ),
        stored(5, EventKind.RUN_FINISHED, {"status": "completed"}),
        stored(6, EventKind.RUN_STARTED, {"task": "把它改成返回 2"}),
        stored(
            7,
            EventKind.MODEL_RESPONSE,
            {
                "content": "第二轮已完成。",
                "finish_reason": "stop",
                "tool_calls": [],
            },
        ),
        stored(8, EventKind.RUN_FINISHED, {"status": "completed"}),
    ]

    seed = restore_conversation(events)

    assert [message.role for message in seed.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.ASSISTANT,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]
    assert seed.messages[0].content == "检查 calculator.py"
    assert seed.messages[1].reasoning_content == "需要先读取文件"
    assert seed.messages[1].tool_calls[0].id == "read-1"
    assert seed.messages[2].tool_call_id == "read-1"
    assert seed.messages[4].content == "把它改成返回 2"
    assert len(seed.observations) == 1
    assert seed.observations[0].status is ObservationStatus.SUCCESS
    assert seed.observations[0].content == "return 1\n"


def test_restore_conversation_accepts_old_model_events_without_reasoning() -> None:
    seed = restore_conversation(
        [
            stored(1, EventKind.RUN_STARTED, {"task": "旧任务"}),
            stored(
                2,
                EventKind.MODEL_RESPONSE,
                {"content": "旧回答", "finish_reason": "stop", "tool_calls": []},
            ),
        ]
    )

    assert seed.messages[-1].reasoning_content is None


def test_restore_conversation_keeps_delivered_runtime_instruction() -> None:
    seed = restore_conversation(
        [
            stored(1, EventKind.RUN_STARTED, {"task": "先检查"}),
            stored(
                2,
                EventKind.INSTRUCTION_DELIVERED,
                {"instruction_id": "next", "content": "不要修改配置"},
            ),
            stored(
                3,
                EventKind.MODEL_RESPONSE,
                {"content": "收到", "finish_reason": "stop", "tool_calls": []},
            ),
        ]
    )

    assert [message.content for message in seed.messages] == [
        "先检查",
        "不要修改配置",
        "收到",
    ]


def test_restore_conversation_rejects_unpaired_tool_observation() -> None:
    events = [
        stored(1, EventKind.RUN_STARTED, {"task": "检查"}),
        stored(
            2,
            EventKind.OBSERVATION_RECEIVED,
            {
                "observation": {
                    "action_id": "missing-action",
                    "status": "success",
                    "summary": "不应存在",
                    "content": "",
                    "metadata": {},
                    "duration_ms": 0,
                },
                "verification": False,
            },
        ),
    ]

    with pytest.raises(ConversationHistoryError, match="missing-action"):
        restore_conversation(events)


def test_restore_conversation_closes_tool_calls_from_an_interrupted_turn() -> None:
    events = [
        stored(1, EventKind.RUN_STARTED, {"task": "运行测试"}),
        stored(
            2,
            EventKind.MODEL_RESPONSE,
            {
                "content": "先运行测试。",
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "command-1",
                        "tool_name": "run_command",
                        "arguments": {"command": "python -m unittest"},
                    }
                ],
            },
        ),
        stored(
            3,
            EventKind.RUN_FINISHED,
            {"status": "stopped", "stop_reason": "user_stopped"},
        ),
        stored(4, EventKind.RUN_STARTED, {"task": "继续"}),
        stored(
            5,
            EventKind.MODEL_RESPONSE,
            {"content": "继续处理。", "finish_reason": "stop", "tool_calls": []},
        ),
    ]

    seed = restore_conversation(events)

    cancelled = seed.observations[0]
    assert cancelled.action_id == "command-1"
    assert cancelled.status is ObservationStatus.ERROR
    assert "user_stopped" in cancelled.summary
    assert [message.role for message in seed.messages] == [
        MessageRole.USER,
        MessageRole.ASSISTANT,
        MessageRole.TOOL,
        MessageRole.USER,
        MessageRole.ASSISTANT,
    ]


def test_restore_conversation_closes_tool_calls_when_process_ended_without_finish_event() -> None:
    events = [
        stored(1, EventKind.RUN_STARTED, {"task": "修改文件"}),
        stored(
            2,
            EventKind.MODEL_RESPONSE,
            {
                "content": None,
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "write-before-crash",
                        "tool_name": "write_file",
                        "arguments": {"path": "app.py", "content": "value = 2\n"},
                    }
                ],
            },
        ),
    ]

    seed = restore_conversation(events)

    recovered = seed.observations[-1]
    assert recovered.action_id == "write-before-crash"
    assert recovered.status is ObservationStatus.ERROR
    assert recovered.metadata["recovered"] is True
    assert recovered.metadata["retry_safe"] is False


def test_restore_conversation_rejects_pending_tool_calls_from_completed_turn() -> None:
    events = [
        stored(1, EventKind.RUN_STARTED, {"task": "运行测试"}),
        stored(
            2,
            EventKind.MODEL_RESPONSE,
            {
                "content": None,
                "finish_reason": "tool_calls",
                "tool_calls": [
                    {
                        "id": "missing-result",
                        "tool_name": "run_command",
                        "arguments": {"command": "python -m unittest"},
                    }
                ],
            },
        ),
        stored(3, EventKind.RUN_FINISHED, {"status": "completed"}),
    ]

    with pytest.raises(ConversationHistoryError, match="missing-result"):
        restore_conversation(events)


def test_restore_conversation_rejects_invalid_user_turn() -> None:
    with pytest.raises(ConversationHistoryError, match="run_started"):
        restore_conversation([stored(1, EventKind.RUN_STARTED, {"task": ""})])


def stored(sequence: int, kind: EventKind, payload: dict[str, object]) -> StoredEvent:
    timestamp = datetime(2026, 8, 29, 9, sequence, tzinfo=UTC)
    return StoredEvent(
        sequence=sequence,
        recorded_at=timestamp,
        event=RunEvent(
            run_id="persisted",
            kind=kind,
            payload=payload,
            occurred_at=timestamp,
        ),
    )
