from __future__ import annotations

from typing import Iterable

from pelgo.adapters.tools.tool_suite import (
    ExtractJDRequirementsTool,
    PrioritiseSkillGapsTool,
    ResearchSkillResourcesTool,
    ScoreCandidateTool,
)
from pelgo.ports.tooling import Tool, ToolRegistry, build_tool_registry


def build_tools() -> ToolRegistry:
    tools: Iterable[Tool] = [
        ExtractJDRequirementsTool(),
        ScoreCandidateTool(),
        PrioritiseSkillGapsTool(),
        ResearchSkillResourcesTool(),
    ]
    return build_tool_registry(tools)
