from __future__ import annotations

from typing import NotRequired, TypedDict

from pelgo.domain.model.agent_evaluation_schema import ToolCallTrace
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsOutput,
    ResearchSkillResourcesOutput,
    ScoreCandidateOutput,
    SkillResource,
)


class ResearchResourceEntry(TypedDict):
    skill: str
    resources: list[SkillResource]


class AgentState(TypedDict):
    job_id: str
    candidate_profile: str
    job_input: str
    requirements: NotRequired[ExtractJDRequirementsOutput]
    score: NotRequired[ScoreCandidateOutput]
    prioritized_gaps: NotRequired[PrioritiseSkillGapsOutput]
    resources: NotRequired[list[ResearchSkillResourcesOutput]]
    researched_resources: NotRequired[list[ResearchResourceEntry]]
    trace_tool_calls: NotRequired[list[ToolCallTrace]]
    gap_skill: NotRequired[str]
    trace_errors: NotRequired[list[dict[str, str | None]]]
    research_started_at: NotRequired[float]
    attempted_research_skills: NotRequired[list[str]]
    research_exhausted: NotRequired[bool]
    total_llm_calls: NotRequired[int]
    fallbacks_triggered: NotRequired[int]
    result: NotRequired[object]
    plan_steps: NotRequired[list[str]]
