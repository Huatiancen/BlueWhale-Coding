"""Environment-backed application configuration."""

from __future__ import annotations

from pathlib import Path

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

from bluewhale_agent.domain.models import Limits


class Settings(BaseSettings):
    """BlueWhale settings loaded without exposing secret values in reprs."""

    model_config = SettingsConfigDict(
        env_prefix="BLUEWHALE_",
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    deepseek_api_key: SecretStr | None = Field(
        default=None,
        validation_alias="DEEPSEEK_API_KEY",
    )
    model: str = "deepseek-v4-flash"
    base_url: str = "https://api.deepseek.com"
    workspace: Path = Field(default_factory=Path.cwd)
    limits: Limits = Field(default_factory=Limits)
