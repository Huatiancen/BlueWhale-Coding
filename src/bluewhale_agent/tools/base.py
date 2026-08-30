"""Interfaces shared by all locally implemented tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field

from pydantic import BaseModel

from bluewhale_agent.domain.models import ObservationStatus
from bluewhale_agent.runtime.changeset import ChangeSet
from bluewhale_agent.runtime.paths import WorkspacePaths


class ToolExecutionError(RuntimeError):
    """A safe, expected failure while running a local tool."""


@dataclass(frozen=True)
class ToolContext:
    """Runtime limits and services available to local tools."""

    paths: WorkspacePaths
    max_file_bytes: int = 1_048_576
    max_read_lines: int = 500
    command_timeout_seconds: float = 120.0
    max_command_output_bytes: int = 20_000
    command_network_allowed: bool = False
    changeset: ChangeSet = field(default_factory=ChangeSet)


@dataclass(frozen=True)
class ToolOutput:
    """Provider-neutral successful output from a local tool."""

    summary: str
    content: str = ""
    metadata: dict[str, object] = field(default_factory=dict)
    status: ObservationStatus = ObservationStatus.SUCCESS


class BaseTool(ABC):
    """Base class for tools with strict Pydantic argument schemas."""

    name: str
    description: str
    arguments_model: type[BaseModel]

    def schema(self) -> dict[str, object]:
        return {
            "type": "function",
            "function": {
                "name": self.name,
                "description": self.description,
                "parameters": self.arguments_model.model_json_schema(),
            },
        }

    async def invoke(self, arguments: dict[str, object], context: ToolContext) -> ToolOutput:
        validated = self.arguments_model.model_validate(arguments)
        return await self.execute(validated, context)

    @abstractmethod
    async def execute(self, arguments: BaseModel, context: ToolContext) -> ToolOutput:
        """Execute one validated tool request."""
