"""Tool discovery, argument validation, permission checks, and dispatch."""

from __future__ import annotations

from time import monotonic

from pydantic import ValidationError

from bluewhale_agent.domain.models import Action, Observation, ObservationStatus
from bluewhale_agent.runtime.paths import PathAccessDeniedError, PathAccessError
from bluewhale_agent.runtime.permissions import PermissionDecision, PermissionPolicy
from bluewhale_agent.tools.base import BaseTool, ToolContext, ToolExecutionError


class ToolRegistry:
    """Dispatch model actions only to explicitly registered local tools."""

    def __init__(
        self,
        *,
        tools: list[BaseTool],
        context: ToolContext,
        permission_policy: PermissionPolicy,
    ) -> None:
        self._tools = {tool.name: tool for tool in tools}
        if len(self._tools) != len(tools):
            raise ValueError("Tool names must be unique")
        self._context = context
        self._permission_policy = permission_policy

    def schemas(self) -> list[dict[str, object]]:
        return [self._tools[name].schema() for name in sorted(self._tools)]

    async def dispatch(self, action: Action) -> Observation:
        started = monotonic()
        tool = self._tools.get(action.tool_name)
        if tool is None:
            return self._error(action, f"Unknown tool: {action.tool_name}", started)

        permission = self._permission_policy.evaluate(action)
        if permission.decision is not PermissionDecision.ALLOW:
            return Observation(
                action_id=action.id,
                status=ObservationStatus.DENIED,
                summary=permission.reason,
                metadata={"permission_decision": permission.decision.value},
                duration_ms=self._duration_ms(started),
            )

        try:
            output = await tool.invoke(action.arguments, self._context)
        except ValidationError:
            return self._error(action, f"Invalid arguments for {action.tool_name}", started)
        except PathAccessDeniedError as exc:
            return Observation(
                action_id=action.id,
                status=ObservationStatus.DENIED,
                summary=str(exc),
                metadata={"permission_decision": PermissionDecision.DENY.value},
                duration_ms=self._duration_ms(started),
            )
        except (PathAccessError, ToolExecutionError, OSError) as exc:
            return self._error(action, str(exc), started)

        return Observation(
            action_id=action.id,
            status=ObservationStatus.SUCCESS,
            summary=output.summary,
            content=output.content,
            metadata=output.metadata,
            duration_ms=self._duration_ms(started),
        )

    @classmethod
    def _error(cls, action: Action, summary: str, started: float) -> Observation:
        return Observation(
            action_id=action.id,
            status=ObservationStatus.ERROR,
            summary=summary,
            duration_ms=cls._duration_ms(started),
        )

    @staticmethod
    def _duration_ms(started: float) -> int:
        return max(0, round((monotonic() - started) * 1000))
