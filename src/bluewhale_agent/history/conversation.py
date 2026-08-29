"""Restore provider-neutral conversation context from durable run events."""

from __future__ import annotations

from dataclasses import dataclass

from pydantic import ValidationError

from bluewhale_agent.domain.events import EventKind
from bluewhale_agent.domain.models import (
    Action,
    Message,
    MessageRole,
    Observation,
    ObservationStatus,
)
from bluewhale_agent.trajectory.store import StoredEvent


class ConversationHistoryError(ValueError):
    """Raised when a trajectory cannot form a valid model conversation."""


@dataclass(frozen=True, slots=True)
class ConversationSeed:
    """Model messages and observations recovered from one local trajectory."""

    messages: tuple[Message, ...]
    observations: tuple[Observation, ...]


def restore_conversation(events: list[StoredEvent]) -> ConversationSeed:
    """Project ordered run events into a tool-protocol-safe conversation seed."""
    messages: list[Message] = []
    observations: list[Observation] = []
    pending_actions: set[str] = set()
    seen_actions: set[str] = set()

    for stored in events:
        kind = stored.event.kind
        payload = stored.event.payload
        if kind is EventKind.RUN_STARTED:
            _require_no_pending(pending_actions, stored.sequence)
            task = payload.get("task")
            if not isinstance(task, str) or not task.strip():
                raise ConversationHistoryError(
                    f"run_started event {stored.sequence} has no valid task"
                )
            messages.append(Message(role=MessageRole.USER, content=task.strip()))
        elif kind is EventKind.MODEL_RESPONSE:
            _require_no_pending(pending_actions, stored.sequence)
            actions = _actions(payload.get("tool_calls"), stored.sequence)
            duplicate = seen_actions.intersection(action.id for action in actions)
            if duplicate:
                raise ConversationHistoryError(
                    f"model_response event {stored.sequence} reuses action id "
                    f"{sorted(duplicate)[0]}"
                )
            content = payload.get("content")
            reasoning = payload.get("reasoning_content")
            if content is not None and not isinstance(content, str):
                raise ConversationHistoryError(
                    f"model_response event {stored.sequence} has invalid content"
                )
            if reasoning is not None and not isinstance(reasoning, str):
                raise ConversationHistoryError(
                    f"model_response event {stored.sequence} has invalid reasoning_content"
                )
            if content is None and not actions:
                raise ConversationHistoryError(
                    f"model_response event {stored.sequence} has no content or tool calls"
                )
            messages.append(
                Message(
                    role=MessageRole.ASSISTANT,
                    content=content,
                    reasoning_content=reasoning,
                    tool_calls=actions,
                )
            )
            action_ids = {action.id for action in actions}
            seen_actions.update(action_ids)
            pending_actions.update(action_ids)
        elif kind is EventKind.OBSERVATION_RECEIVED:
            if payload.get("verification") is True:
                continue
            observation = _observation(payload.get("observation"), stored.sequence)
            if observation.action_id not in pending_actions:
                raise ConversationHistoryError(
                    f"observation event {stored.sequence} references unpaired action "
                    f"{observation.action_id}"
                )
            observations.append(observation)
            messages.append(
                Message(
                    role=MessageRole.TOOL,
                    content=observation.model_dump_json(),
                    tool_call_id=observation.action_id,
                )
            )
            pending_actions.remove(observation.action_id)
        elif kind is EventKind.RUN_FINISHED and pending_actions:
            status = payload.get("status")
            if status not in {"stopped", "failed"}:
                _require_no_pending(pending_actions, stored.sequence)
            reason = payload.get("stop_reason")
            reason_label = reason if isinstance(reason, str) and reason else str(status)
            for action_id in sorted(pending_actions):
                observation = Observation(
                    action_id=action_id,
                    status=ObservationStatus.ERROR,
                    summary=f"Previous tool call ended without a result: {reason_label}",
                    content="The previous run was interrupted before this tool returned.",
                    metadata={"recovered": True, "stop_reason": reason_label},
                    duration_ms=0,
                )
                observations.append(observation)
                messages.append(
                    Message(
                        role=MessageRole.TOOL,
                        content=observation.model_dump_json(),
                        tool_call_id=action_id,
                    )
                )
            pending_actions.clear()

    _require_no_pending(pending_actions, None)
    return ConversationSeed(messages=tuple(messages), observations=tuple(observations))


def _actions(value: object, sequence: int) -> tuple[Action, ...]:
    if value is None:
        return ()
    if not isinstance(value, list):
        raise ConversationHistoryError(
            f"model_response event {sequence} has invalid tool_calls"
        )
    try:
        return tuple(Action.model_validate(item) for item in value)
    except ValidationError as error:
        raise ConversationHistoryError(
            f"model_response event {sequence} has invalid tool_calls"
        ) from error


def _observation(value: object, sequence: int) -> Observation:
    try:
        return Observation.model_validate(value)
    except ValidationError as error:
        raise ConversationHistoryError(
            f"observation event {sequence} has invalid payload"
        ) from error


def _require_no_pending(pending: set[str], sequence: int | None) -> None:
    if not pending:
        return
    location = "at end of trajectory" if sequence is None else f"before event {sequence}"
    raise ConversationHistoryError(
        f"unpaired tool action {sorted(pending)[0]} remains {location}"
    )
