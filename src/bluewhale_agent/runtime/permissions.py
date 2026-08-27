"""Explicit local-tool permission decisions."""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from bluewhale_agent.domain.models import Action


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
    """Allow this module's read-only tools and deny everything else."""

    READ_ONLY_TOOLS = frozenset({"list_files", "read_file", "search_text"})

    def evaluate(self, action: Action) -> PermissionResult:
        if action.tool_name in self.READ_ONLY_TOOLS:
            return PermissionResult(
                decision=PermissionDecision.ALLOW,
                reason="Known read-only workspace tool",
            )
        return PermissionResult(
            decision=PermissionDecision.DENY,
            reason=f"Tool is not allowed by the current policy: {action.tool_name}",
        )
