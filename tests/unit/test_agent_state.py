from datetime import UTC, datetime

import pytest

from bluewhale_agent.agent.state import AgentState, InvalidTransition
from bluewhale_agent.config import Settings
from bluewhale_agent.domain.models import (
    Action,
    Limits,
    Message,
    MessageRole,
    Observation,
    ObservationStatus,
    RunStatus,
    StopReason,
)


def test_agent_state_completes_after_successful_verification() -> None:
    state = AgentState.start("repair bug", Limits(max_steps=2))

    state.mark_running()
    state.begin_verification()
    state.complete(verified=True)

    assert state.status is RunStatus.COMPLETED
    assert state.verified is True
    assert state.can_continue is False


def test_failed_verification_returns_agent_to_running() -> None:
    state = AgentState.start("repair bug", Limits(max_steps=2))
    state.mark_running()
    state.begin_verification()

    state.complete(verified=False)

    assert state.status is RunStatus.RUNNING
    assert state.verified is False
    assert state.repair_attempts == 1


def test_reaching_step_limit_stops_the_run() -> None:
    state = AgentState.start("repair bug", Limits(max_steps=2))
    state.mark_running()

    state.record_step()
    state.record_step()

    assert state.status is RunStatus.STOPPED
    assert state.stop_reason is StopReason.STEP_LIMIT
    assert state.can_continue is False


def test_invalid_transition_is_rejected() -> None:
    state = AgentState.start("repair bug", Limits(max_steps=2))

    with pytest.raises(InvalidTransition, match="INITIALIZING.*VERIFYING"):
        state.begin_verification()


def test_action_and_observation_serialize_without_sdk_types() -> None:
    requested_at = datetime(2026, 8, 27, tzinfo=UTC)
    action = Action(
        id="call_1",
        tool_name="read_file",
        arguments={"path": "src/app.py", "start_line": 1},
        requested_at=requested_at,
    )
    observation = Observation(
        action_id=action.id,
        status=ObservationStatus.SUCCESS,
        summary="Read 10 lines",
        content="print('hello')",
        metadata={"line_count": 10},
        duration_ms=12,
    )

    assert action.model_dump(mode="json")["requested_at"] == "2026-08-27T00:00:00Z"
    assert observation.model_dump(mode="json")["status"] == "success"


def test_message_preserves_reasoning_for_tool_call_history() -> None:
    message = Message(
        role=MessageRole.ASSISTANT,
        content=None,
        reasoning_content="inspect the failing file",
        tool_calls=[
            Action(
                id="call_1",
                tool_name="read_file",
                arguments={"path": "src/app.py"},
            )
        ],
    )

    assert message.reasoning_content == "inspect the failing file"
    assert message.tool_calls[0].tool_name == "read_file"


def test_settings_read_credentials_without_exposing_secret(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DEEPSEEK_API_KEY", "test-secret")
    monkeypatch.setenv("BLUEWHALE_MODEL", "test-model")

    settings = Settings()

    assert settings.deepseek_api_key is not None
    assert settings.deepseek_api_key.get_secret_value() == "test-secret"
    assert settings.model == "test-model"
    assert "test-secret" not in repr(settings)


def test_settings_default_to_cost_effective_deepseek_flash() -> None:
    settings = Settings(_env_file=None)

    assert settings.model == "deepseek-v4-flash"
