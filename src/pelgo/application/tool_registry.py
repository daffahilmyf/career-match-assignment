from __future__ import annotations

from typing import Iterable

from pelgo.adapters.tools.tool_suite import (
    ExtractJDRequirementsTool,
    PrioritiseSkillGapsTool,
    ResearchSkillResourcesTool,
    ScoreCandidateTool,
)
from pelgo.ports.llm import LLMClient
from pelgo.ports.tooling import Tool, ToolRegistry, build_tool_registry
from pelgo.application.config import AppSettings


def build_tools(llm: LLMClient | None = None, settings: AppSettings | None = None) -> ToolRegistry:
    settings = settings or AppSettings()
    tools: Iterable[Tool] = [
        ExtractJDRequirementsTool(llm=llm, timeout_seconds=settings.research_time_cap_seconds),
        ScoreCandidateTool(),
        PrioritiseSkillGapsTool(),
        ResearchSkillResourcesTool(timeout_seconds=settings.research_time_cap_seconds),
    ]
    return build_tool_registry(tools)
