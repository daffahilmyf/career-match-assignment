from __future__ import annotations

from pelgo.adapters.persistence.postgres_job_repository import PostgresJobRepository, create_pg_engine
from pelgo.adapters.tools.tool_suite import (
    ExtractJDRequirementsTool,
    PrioritiseSkillGapsTool,
    ResearchSkillResourcesTool,
    ScoreCandidateTool,
)
from pelgo.application.config import AppSettings
from pelgo.ports.llm import LLMClient
from pelgo.ports.tooling import ToolRegistry, build_tool_registry


def build_tools(llm: LLMClient, settings: AppSettings) -> ToolRegistry:
    repository = None
    if settings.database_url:
        repository = PostgresJobRepository(create_pg_engine(settings.database_url))

    return build_tool_registry(
        [
            ExtractJDRequirementsTool(llm=llm, timeout_seconds=10, repository=repository),
            ScoreCandidateTool(),
            PrioritiseSkillGapsTool(llm=llm),
            ResearchSkillResourcesTool(timeout_seconds=10, llm=llm, max_resources=settings.mit_course_limit),
        ]
    )
