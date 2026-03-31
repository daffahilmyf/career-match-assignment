from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field, field_validator

from pelgo.domain.model.candidate_profile import CandidateProfile


class CandidateCreateResponse(BaseModel):
    candidate_id: str
    profile: CandidateProfile


class MatchesCreateRequest(BaseModel):
    candidate_id: str
    jd_sources: list[str] = Field(..., min_length=1, max_length=10)

    @field_validator("jd_sources")
    @classmethod
    def _strip_and_validate_sources(cls, value: list[str]) -> list[str]:
        cleaned = [item.strip() for item in value if item and item.strip()]
        if not cleaned:
            raise ValueError("jd_sources must contain at least one non-empty JD text or URL")
        if len(cleaned) > 10:
            raise ValueError("jd_sources can contain at most 10 items")
        return cleaned


class MatchCreateItem(BaseModel):
    job_id: str
    status: str


class MatchesCreateResponse(BaseModel):
    jobs: list[MatchCreateItem]


class MatchStatusResponse(BaseModel):
    job_id: str
    status: str
    result: dict[str, Any] | None = None
    agent_trace: dict[str, Any] | None = None
    error: str | None = None


class MatchListItem(BaseModel):
    job_id: str
    status: str


class MatchListResponse(BaseModel):
    items: list[MatchListItem]
    limit: int
    offset: int
