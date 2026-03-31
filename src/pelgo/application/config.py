from __future__ import annotations

from pydantic_settings import BaseSettings, SettingsConfigDict


class AppSettings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="", extra="ignore")

    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None

    research_time_cap_seconds: int = 25
    top_gap_limit: int = 3
