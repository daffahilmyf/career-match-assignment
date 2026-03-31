from __future__ import annotations

from pydantic import BaseModel, Field


class CandidateProfile(BaseModel):
    name: str | None = None
    email: str | None = None
    skills: list[str] = Field(default_factory=list)
    education: list[str] = Field(default_factory=list)
    experience: list[str] = Field(default_factory=list)
    years_experience: int = 0
