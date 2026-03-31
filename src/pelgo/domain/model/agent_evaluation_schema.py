from __future__ import annotations

from typing import List
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator, model_validator

from .shared_types import (
    ConfidenceLevel,
    NonNegativeInt,
    PositiveInt,
    ResourceType,
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
    type: ResourceType


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
    call_id: str


class AgentExecutionTrace(BaseModel):
    model_config = ConfigDict(extra="forbid")

    tool_calls: List[ToolCallTrace]
    total_llm_calls: NonNegativeInt
    fallbacks_triggered: NonNegativeInt


class AgentEvaluationResult(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    job_id: UUID = Field(..., serialization_alias="job_id", validation_alias="job_id")
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
        ...,
        serialization_alias="matched_skills",
        validation_alias="matched_skills",
        min_length=1,
    )
    missing_skill_tags: List[str] = Field(
        ...,
        serialization_alias="gap_skills",
        validation_alias="gap_skills",
        min_length=1,
    )
    summary: str = Field(
        ...,
        min_length=80,
        max_length=1200,
        serialization_alias="reasoning",
        validation_alias="reasoning",
    )
    learning_plan: List[LearningPlanItem] = Field(
        ...,
        serialization_alias="learning_plan",
        validation_alias="learning_plan",
        min_length=1,
        max_length=5,
    )
    execution_trace: AgentExecutionTrace = Field(
        ..., serialization_alias="agent_trace", validation_alias="agent_trace"
    )

    @field_validator("matched_skill_tags", "missing_skill_tags")
    @classmethod
    def normalize_skill_tags(cls, value: List[str]) -> List[str]:
        normalized: List[str] = []
        seen: set[str] = set()
        for skill in value:
            cleaned = skill.strip().lower()
            if not cleaned or cleaned in seen:
                continue
            seen.add(cleaned)
            normalized.append(cleaned)
        return normalized

    @model_validator(mode="after")
    def require_trace_evidence(self) -> "AgentEvaluationResult":
        tool_calls_count = len(self.execution_trace.tool_calls)
        if tool_calls_count == 0 and self.execution_trace.total_llm_calls == 0:
            raise ValueError(
                "agent_trace must include at least one tool call or nonzero total_llm_calls"
            )
        return self
