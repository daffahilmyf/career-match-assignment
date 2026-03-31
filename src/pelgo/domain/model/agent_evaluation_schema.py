from __future__ import annotations

from typing import List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl

from .shared_types import (
    ConfidenceLevel,
    NonNegativeInt,
    PositiveInt,
    ScorePercent,
)


class DimensionMatchScores(BaseModel):
    skills: ScorePercent
    experience: ScorePercent
    seniority_fit: ScorePercent


class LearningResource(BaseModel):
    title: str
    url: HttpUrl
    estimated_hours: PositiveInt
    type: str


class LearningPlanItem(BaseModel):
    skill: str
    priority_rank: PositiveInt
    estimated_match_gain_pct: ScorePercent
    resources: List[LearningResource]
    rationale: str


class ToolCallTrace(BaseModel):
    tool: str
    status: str
    latency_ms: NonNegativeInt


class AgentExecutionTrace(BaseModel):
    tool_calls: List[ToolCallTrace]
    total_llm_calls: NonNegativeInt
    fallbacks_triggered: NonNegativeInt


class AgentEvaluationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True)

    job_id: UUID = Field(..., serialization_alias="job_id",
                         validation_alias="job_id")
    overall_match_score: ScorePercent = Field(
        ..., serialization_alias="overall_score", validation_alias="overall_score"
    )
    confidence_level: ConfidenceLevel = Field(
        ..., serialization_alias="confidence", validation_alias="confidence"
    )
    dimension_match_scores: DimensionMatchScores = Field(
        ..., serialization_alias="dimension_scores", validation_alias="dimension_scores"
    )
    matched_skill_tags: List[str] = Field(
        ..., serialization_alias="matched_skills", validation_alias="matched_skills"
    )
    missing_skill_tags: List[str] = Field(
        ..., serialization_alias="gap_skills", validation_alias="gap_skills"
    )
    summary: str = Field(
        ..., min_length=1, serialization_alias="reasoning", validation_alias="reasoning"
    )
    learning_plan: List[LearningPlanItem] = Field(
        ..., serialization_alias="learning_plan", validation_alias="learning_plan"
    )
    execution_trace: AgentExecutionTrace = Field(
        ..., serialization_alias="agent_trace", validation_alias="agent_trace"
    )
