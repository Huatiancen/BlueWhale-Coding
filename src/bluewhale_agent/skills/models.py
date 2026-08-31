"""Validated models for local Agent Skills packages."""

from __future__ import annotations

from enum import StrEnum
from pathlib import Path

from pydantic import BaseModel, ConfigDict

MAX_ACTIVE_SKILLS = 16


class SkillScope(StrEnum):
    USER = "user"
    PROJECT = "project"


class SkillDescriptor(BaseModel):
    model_config = ConfigDict(frozen=True)

    name: str
    description: str
    source: str
    scope: SkillScope
    path: Path
    boundary: Path
    disable_model_invocation: bool = False


class LoadedSkill(BaseModel):
    model_config = ConfigDict(frozen=True)

    descriptor: SkillDescriptor
    instructions: str
    resources: tuple[str, ...] = ()
