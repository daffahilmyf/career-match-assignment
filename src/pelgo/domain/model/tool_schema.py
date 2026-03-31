from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, Field, HttpUrl

from .shared_types import (
    ConfidenceLevel,
    PositiveInt,
    ScorePercent,
)


class ExtractJDRequirementsInput(BaseModel):
    job_url_or_text: str = Field(..., min_length=1)


class ExtractJDRequirementsOutput(BaseModel):
    required_skills: List[str]
    nice_to_have_skills: List[str]
    seniority_level: str
    domain: str
    responsibilities: List[str]


class ScoreCandidateInput(BaseModel):
    candidate_profile: str = Field(..., min_length=1)
    requirements: ExtractJDRequirementsOutput


class ScoreCandidateDimensionScores(BaseModel):
    skills: ScorePercent
    experience: ScorePercent
    seniority_fit: ScorePercent


class ScoreCandidateOutput(BaseModel):
    overall_score: ScorePercent
    dimension_scores: ScoreCandidateDimensionScores
    matched_skills: List[str]
    gap_skills: List[str]
    confidence: ConfidenceLevel


class ResearchSkillResourcesInput(BaseModel):
    skill_name: str = Field(..., min_length=1)
    seniority_context: Optional[str] = None


class ResourceType(str, Enum):
    course = "course"
    project = "project"
    cert = "cert"
    doc = "doc"


class SkillResource(BaseModel):
    title: str
    url: HttpUrl
    estimated_hours: PositiveInt
    type: ResourceType


class ResearchSkillResourcesOutput(BaseModel):
    resources: List[SkillResource]
    relevance_score: ScorePercent


class PrioritiseSkillGapsInput(BaseModel):
    gap_skills: List[str]
    job_market_context: str = Field(..., min_length=1)


class PrioritisedSkillGap(BaseModel):
    skill: str
    priority_rank: PositiveInt
    estimated_match_gain_pct: ScorePercent
    rationale: str


class PrioritiseSkillGapsOutput(BaseModel):
    ranked_skills: List[PrioritisedSkillGap]
