"""Explicit local-tool permission decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from bluewhale_agent.domain.models import Action
from bluewhale_agent.runtime.paths import PathAccessError, WorkspacePaths


class PermissionDecision(StrEnum):
    """Possible decisions for a requested local action."""

    ALLOW = "allow"
    ASK = "ask"
    DENY = "deny"


class PermissionResult(BaseModel):
    """Permission decision plus a user-facing reason."""

    model_config = ConfigDict(frozen=True)

    decision: PermissionDecision
    reason: str


class PermissionPolicy:
    """Classify local tool actions before execution."""

    READ_ONLY_TOOLS = frozenset({"get_diff", "list_files", "read_file", "search_text"})

    def __init__(self, paths: WorkspacePaths | None = None) -> None:
        self._paths = paths

    def evaluate(self, action: Action) -> PermissionResult:
        if action.tool_name in self.READ_ONLY_TOOLS:
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="Known read-only workspace tool",
            )
        if action.tool_name == "apply_patch":
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="Patch requires one exact workspace match",
            )
        if action.tool_name == "write_file":
            return self._evaluate_write_file(action)
        return PermissionResult(
            decision=PermissionDecision.DENY,
            reason=f"Tool is not allowed by the current policy: {action.tool_name}",
        )

    def _evaluate_write_file(self, action: Action) -> PermissionResult:
        requested = action.arguments.get("path")
        if not isinstance(requested, str) or self._paths is None:
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason="File write requires explicit approval",
            )
        try:
            target = self._paths.resolve(requested, must_exist=False)
        except PathAccessError as exc:
            return PermissionResult(decision=PermissionDecision.DENY, reason=str(exc))
        if target.exists():
            return PermissionResult(
                decision=PermissionDecision.ASK,
                reason="Overwriting an existing file requires approval",
            )
        return PermissionResult(
            decision=PermissionDecision.ALLOW,
            reason="Creating a new workspace file is allowed",
        )
