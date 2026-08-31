"""Controlled model access to already discovered local Skills."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from bluewhale_agent.skills.catalog import SkillCatalog, SkillCatalogError
from bluewhale_agent.skills.models import LoadedSkill
from bluewhale_agent.tools.base import BaseTool, ToolContext, ToolExecutionError, ToolOutput


class LoadSkillArguments(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=64)


class LoadSkillTool(BaseTool):
    name = "load_skill"
    description = (
        "Load the complete instructions for one available Skill when its description "
        "matches the current task."
    )
    arguments_model = LoadSkillArguments

    def __init__(self, catalog: SkillCatalog) -> None:
        self._catalog = catalog

    async def execute(
        self,
        arguments: BaseModel,
        context: ToolContext,
    ) -> ToolOutput:
        del context
        assert isinstance(arguments, LoadSkillArguments)
        try:
            loaded = self._catalog.load(arguments.name)
        except SkillCatalogError as error:
            raise ToolExecutionError(str(error)) from error
        descriptor = loaded.descriptor
        content = render_loaded_skill(loaded)
        return ToolOutput(
            summary=f"Loaded Skill: {descriptor.name}",
            content=content,
            metadata={
                "skill_name": descriptor.name,
                "source": descriptor.source,
                "scope": descriptor.scope.value,
                "summary": descriptor.description,
                "resource_count": len(loaded.resources),
            },
        )


def render_loaded_skill(loaded: LoadedSkill) -> str:
    resource_section = "\n".join(f"- {path}" for path in loaded.resources)
    content = loaded.instructions
    if resource_section:
        content += f"\n\n# Available Skill resources\n{resource_section}\n"
    return content
