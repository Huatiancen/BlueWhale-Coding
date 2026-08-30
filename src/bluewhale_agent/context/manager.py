"""Deterministic, budget-aware assembly of provider-neutral messages."""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass

from bluewhale_agent.context.compaction import summarize_conversation
from bluewhale_agent.context.workspace_map import WorkspaceMap
from bluewhale_agent.domain.models import (
    Message,
    MessageRole,
    Observation,
    ObservationStatus,
    RunStatus,
)


class ContextBudgetError(ValueError):
    """Raised when structural tool-call data alone exceeds the context budget."""


@dataclass
class _MessageGroup:
    messages: list[Message]
    priority: int
    required: bool


def context_char_count(messages: Sequence[Message]) -> int:
    """Return a deterministic approximation used for local context limits."""

    total = 0
    for message in messages:
        total += len(message.content or "")
        total += len(message.reasoning_content or "")
        total += len(message.tool_call_id or "")
        for action in message.tool_calls:
            total += len(action.id) + len(action.tool_name)
            total += len(json.dumps(action.arguments, ensure_ascii=False, default=str))
    return total


class ContextManager:
    """Assemble context sections and compact observations without breaking protocol pairs."""

    def __init__(self, *, max_chars: int, recent_observations: int = 5) -> None:
        if max_chars <= 0:
            raise ValueError("max_chars must be positive")
        if recent_observations <= 0:
            raise ValueError("recent_observations must be positive")
        self._max_chars = max_chars
        self._recent_observations = recent_observations

    def build(
        self,
        *,
        system_prompt: str,
        task: str,
        status: RunStatus | str,
        unresolved_errors: Sequence[str],
        working_set: Mapping[str, str],
        workspace_map: WorkspaceMap,
        history: Sequence[Message],
        observations: Sequence[Observation],
        prior_history: Sequence[Message] = (),
        project_instructions: str = "",
    ) -> list[Message]:
        normalized_prior = self._normalize_observations(prior_history, observations)
        normalized_history = self._normalize_observations(history, observations)
        sections = self._section_groups(
            system_prompt=system_prompt,
            task=task,
            status=status,
            unresolved_errors=unresolved_errors,
            working_set=working_set,
            workspace_map=workspace_map,
            project_instructions=project_instructions,
        )
        groups = [sections[0]]
        if normalized_prior:
            groups.append(
                _MessageGroup(
                    messages=[
                        Message(
                            role=MessageRole.SYSTEM,
                            content=summarize_conversation(normalized_prior),
                        )
                    ],
                    priority=700,
                    required=True,
                )
            )
        groups.extend(self._history_groups(normalized_prior, observations))
        groups.extend(sections[1:])
        groups.extend(self._history_groups(normalized_history, observations))
        return self._fit_budget(groups)

    @staticmethod
    def _section_groups(
        *,
        system_prompt: str,
        task: str,
        status: RunStatus | str,
        unresolved_errors: Sequence[str],
        working_set: Mapping[str, str],
        workspace_map: WorkspaceMap,
        project_instructions: str,
    ) -> list[_MessageGroup]:
        status_value = status.value if isinstance(status, RunStatus) else status
        groups = [
            _MessageGroup(
                messages=[Message(role=MessageRole.SYSTEM, content=system_prompt)],
                priority=1_000,
                required=True,
            ),
            _MessageGroup(
                messages=[
                    Message(
                        role=MessageRole.USER,
                        content=f"# Current task\n{task}\n\n# Run status\n{status_value}",
                    )
                ],
                priority=900,
                required=True,
            ),
        ]
        if project_instructions:
            groups.insert(
                1,
                _MessageGroup(
                    messages=[
                        Message(
                            role=MessageRole.SYSTEM,
                            content="# Project instructions (AGENTS.md)\n"
                            + project_instructions,
                        )
                    ],
                    priority=950,
                    required=True,
                ),
            )
        if unresolved_errors:
            content = "# Unresolved errors\n" + "\n".join(
                f"- {error}" for error in unresolved_errors
            )
            groups.append(
                _MessageGroup(
                    messages=[Message(role=MessageRole.USER, content=content)],
                    priority=850,
                    required=True,
                )
            )
        if working_set:
            lines = ["# Working set"]
            for path in sorted(working_set):
                lines.extend((f"## {path}", working_set[path]))
            groups.append(
                _MessageGroup(
                    messages=[Message(role=MessageRole.USER, content="\n".join(lines))],
                    priority=80,
                    required=False,
                )
            )
        groups.append(
            _MessageGroup(
                messages=[Message(role=MessageRole.USER, content=workspace_map.render())],
                priority=60,
                required=False,
            )
        )
        return groups

    def _normalize_observations(
        self,
        history: Sequence[Message],
        observations: Sequence[Observation],
    ) -> list[Message]:
        by_id = {observation.action_id: observation for observation in observations}
        recent_ids = {
            observation.action_id for observation in observations[-self._recent_observations :]
        }
        normalized: list[Message] = []
        for message in history:
            observation = by_id.get(message.tool_call_id or "")
            if message.role is not MessageRole.TOOL or observation is None:
                normalized.append(message)
                continue
            keep_body = (
                observation.action_id in recent_ids
                or observation.status is not ObservationStatus.SUCCESS
            )
            normalized.append(
                message.model_copy(
                    update={"content": self._observation_content(observation, keep_body)}
                )
            )
        return normalized

    @staticmethod
    def _observation_content(observation: Observation, keep_body: bool) -> str:
        payload: dict[str, object] = {
            "status": observation.status.value,
            "summary": observation.summary,
        }
        if keep_body:
            payload["content"] = observation.content
            payload["metadata"] = observation.metadata
        else:
            artifact = observation.metadata.get("artifact_path")
            if artifact is not None:
                payload["artifact_path"] = artifact
        return json.dumps(payload, ensure_ascii=False, default=str, separators=(",", ":"))

    def _history_groups(
        self,
        history: Sequence[Message],
        observations: Sequence[Observation],
    ) -> list[_MessageGroup]:
        by_id = {observation.action_id: observation for observation in observations}
        recent_ids = {
            observation.action_id for observation in observations[-self._recent_observations :]
        }
        groups: list[_MessageGroup] = []
        index = 0
        while index < len(history):
            message = history[index]
            grouped = [message]
            action_ids = {action.id for action in message.tool_calls}
            if message.role is MessageRole.ASSISTANT and action_ids:
                cursor = index + 1
                while cursor < len(history):
                    candidate = history[cursor]
                    if candidate.role is not MessageRole.TOOL:
                        break
                    if candidate.tool_call_id not in action_ids:
                        break
                    grouped.append(candidate)
                    cursor += 1
                index = cursor
            else:
                index += 1

            tool_ids = {
                item.tool_call_id
                for item in grouped
                if item.role is MessageRole.TOOL and item.tool_call_id is not None
            }
            is_recent = bool(tool_ids & recent_ids)
            has_failure = any(
                by_id[tool_id].status is not ObservationStatus.SUCCESS
                for tool_id in tool_ids
                if tool_id in by_id
            )
            groups.append(
                _MessageGroup(
                    messages=grouped,
                    priority=850 if has_failure else 800 if is_recent else 20,
                    required=is_recent or has_failure,
                )
            )
        return groups

    def _fit_budget(self, groups: list[_MessageGroup]) -> list[Message]:
        selected = list(groups)
        while self._group_cost(selected) > self._max_chars:
            optional = [group for group in selected if not group.required]
            if not optional:
                break
            victim = min(optional, key=lambda group: group.priority)
            selected.remove(victim)

        while self._group_cost(selected) > self._max_chars:
            over = self._group_cost(selected) - self._max_chars
            candidate = self._compression_candidate(selected)
            if candidate is None:
                raise ContextBudgetError(
                    "Tool-call structure exceeds the configured context character budget"
                )
            group, message_index = candidate
            message = group.messages[message_index]
            content = message.content or ""
            target = max(0, len(content) - over)
            group.messages[message_index] = message.model_copy(
                update={"content": self._truncate(content, target)}
            )

        return [message for group in selected for message in group.messages]

    @staticmethod
    def _group_cost(groups: Sequence[_MessageGroup]) -> int:
        return context_char_count([message for group in groups for message in group.messages])

    @staticmethod
    def _compression_candidate(
        groups: Sequence[_MessageGroup],
    ) -> tuple[_MessageGroup, int] | None:
        candidates = [
            (group, index)
            for group in groups
            for index, message in enumerate(group.messages)
            if message.content
        ]
        if not candidates:
            return None
        lowest_priority = min(group.priority for group, _ in candidates)
        lowest_candidates = [
            item for item in candidates if item[0].priority == lowest_priority
        ]
        return max(
            lowest_candidates,
            key=lambda item: len(item[0].messages[item[1]].content or ""),
        )

    @staticmethod
    def _truncate(content: str, max_chars: int) -> str:
        if len(content) <= max_chars:
            return content
        if max_chars <= 0:
            return ""
        marker = "\n...[context truncated]...\n"
        if max_chars <= len(marker):
            return marker[:max_chars]
        available = max_chars - len(marker)
        head = (available * 2) // 3
        tail = available - head
        return content[:head] + marker + content[-tail:] if tail else content[:head] + marker
