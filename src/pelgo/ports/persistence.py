from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Protocol


@dataclass(frozen=True)
class JobRecord:
    id: str
    candidate_id: str
    jd_source: str
    attempts: int


@dataclass(frozen=True)
class MatchResultRecord:
    job_id: str
    status: str
    agent_output: dict[str, Any] | None
    agent_trace: dict[str, Any] | None
    last_error: str | None


@dataclass(frozen=True)
class MatchListRecord:
    job_id: str
    status: str


@dataclass(frozen=True)
class JDCacheRecord:
    jd_url: str
    content_hash: str
    requirements_json: dict[str, Any]


class JobRepositoryPort(Protocol):
    def claim_next_job(self) -> JobRecord | None: ...

    def create_candidate(self, profile_json: dict[str, Any]) -> str: ...

    def create_match_job(self, candidate_id: str, jd_source: str) -> str: ...

    def mark_completed(self, job_id: str, output: dict[str, Any], trace: dict[str, Any]) -> None: ...

    def mark_failed(
        self,
        job_id: str,
        error: str,
        attempts: int,
        retry_after_seconds: int,
        trace: dict[str, Any] | None,
    ) -> None: ...

    def requeue_job(self, job_id: str) -> bool: ...

    def get_candidate_profile(self, candidate_id: str) -> dict[str, Any]: ...

    def get_match_result(self, job_id: str) -> MatchResultRecord | None: ...

    def list_match_jobs(self, limit: int, offset: int, status: str | None) -> list[MatchListRecord]: ...

    def get_cached_jd(self, jd_url: str) -> JDCacheRecord | None: ...

    def upsert_cached_jd(self, jd_url: str, content_hash: str, requirements_json: dict[str, Any]) -> None: ...
