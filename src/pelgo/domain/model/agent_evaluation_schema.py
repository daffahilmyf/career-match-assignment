from __future__ import annotations

from typing import List

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, PositiveInt
from pydantic import NonNegativeInt

from pelgo.domain.model.shared_types import ConfidenceLevel, ScorePercent
from pelgo.domain.model.tool_schema import ResourceType, ScoreCandidateDimensionScores


class LearningResource(BaseModel):
    title: str
    url: HttpUrl
    estimated_hours: PositiveInt
    type: ResourceType


class LearningPlanItem(BaseModel):
    skill: str
    priority_rank: PositiveInt
    estimated_match_gain_pct: PositiveInt
    resources: List[LearningResource]
    rationale: str


class ToolCallTrace(BaseModel):
    tool: str
    status: str
    latency_ms: NonNegativeInt


class AgentTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_calls: List[ToolCallTrace]
    total_llm_calls: NonNegativeInt
    fallbacks_triggered: NonNegativeInt


class AgentEvaluationResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    job_id: str
    overall_score: ScorePercent
    confidence: ConfidenceLevel
    dimension_scores: ScoreCandidateDimensionScores
    matched_skills: List[str]
    gap_skills: List[str]
    reasoning: str = Field(min_length=1, max_length=1200)
    learning_plan: List[LearningPlanItem]
    agent_trace: AgentTrace
