from __future__ import annotations

import operator
from typing import Annotated, NotRequired, TypedDict

from pelgo.domain.model.agent_evaluation_schema import ToolCallTrace
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsOutput,
    ResearchSkillResourcesOutput,
    ScoreCandidateOutput,
)


class AgentState(TypedDict):
    candidate_profile: str
    job_input: str
    requirements: NotRequired[ExtractJDRequirementsOutput]
    score: NotRequired[ScoreCandidateOutput]
    prioritized_gaps: NotRequired[PrioritiseSkillGapsOutput]
    resources: NotRequired[Annotated[list[ResearchSkillResourcesOutput], operator.add]]
    trace_tool_calls: NotRequired[Annotated[list[ToolCallTrace], operator.add]]
    gap_skill: NotRequired[str]
    trace_last_error: NotRequired[dict[str, str | None]]
