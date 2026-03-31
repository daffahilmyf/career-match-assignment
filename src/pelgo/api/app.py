from __future__ import annotations

import base64
import io
import re
from typing import Any

from fastapi import FastAPI, HTTPException, Query
from pypdf import PdfReader

from pelgo.api.schemas import (
    CandidateCreateRequest,
    CandidateCreateResponse,
    MatchCreateItem,
    MatchListItem,
    MatchListResponse,
    MatchesCreateRequest,
    MatchesCreateResponse,
    MatchStatusResponse,
)
from pelgo.application.config import AppSettings
from pelgo.adapters.persistence.postgres_job_repository import PostgresJobRepository, create_pg_engine
from pelgo.application.logging import configure_logging, get_logger, log_event


def _extract_profile_from_text(resume_text: str) -> dict[str, Any]:
    lines = [line.strip() for line in resume_text.splitlines() if line.strip()]
    name = lines[0] if lines else None
    email_match = re.search(r"[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}", resume_text, re.IGNORECASE)
    email = email_match.group(0) if email_match else None

    skills: list[str] = []
    for line in lines:
        if re.match(r"^(skills|technical skills)\b", line, re.IGNORECASE):
            parts = re.split(r"[:,-]", line, maxsplit=1)
            if len(parts) > 1:
                skills = [s.strip() for s in re.split(r"[,/|]", parts[1]) if s.strip()]
            break

    education = [
        line
        for line in lines
        if re.search(r"\b(university|college|b\.sc|bachelor|m\.sc|master|phd)\b", line, re.I)
    ]

    experience_lines = [
        line
        for line in lines
        if re.search(r"\b(company|engineer|developer|manager|lead|intern)\b", line, re.I)
    ]

    years_match = re.findall(r"(\d+)\+?\s+years?", resume_text, re.IGNORECASE)
    years_experience = max([int(val) for val in years_match], default=0)

    return {
        "name": name,
        "email": email,
        "skills": skills,
        "education": education,
        "experience": experience_lines,
        "years_experience": years_experience,
    }


def _extract_text_from_pdf(base64_payload: str) -> str:
    try:
        pdf_bytes = base64.b64decode(base64_payload)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="Invalid base64 for resume_pdf_base64") from exc
    reader = PdfReader(io.BytesIO(pdf_bytes))
    text_parts = []
    for page in reader.pages:
        text_parts.append(page.extract_text() or "")
    return "\n".join(text_parts).strip()


def create_app() -> FastAPI:
    settings = AppSettings()
    if not settings.database_url:
        raise RuntimeError("DATABASE_URL must be set to run the API")

    configure_logging()
    logger = get_logger("pelgo.api")

    engine = create_pg_engine(settings.database_url)
    repo = PostgresJobRepository(engine)

    app = FastAPI(title="Pelgo Matching API", version="0.1.0")

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/candidate", response_model=CandidateCreateResponse)
    def create_candidate(payload: CandidateCreateRequest) -> CandidateCreateResponse:
        resume_text = payload.resume_text
        if resume_text is None and payload.resume_pdf_base64 is None:
            raise HTTPException(status_code=400, detail="resume_text or resume_pdf_base64 is required")
        if resume_text is None:
            resume_text = _extract_text_from_pdf(payload.resume_pdf_base64 or "")
        if not resume_text:
            raise HTTPException(status_code=400, detail="Resume text could not be extracted")
        profile = _extract_profile_from_text(resume_text)
        candidate_id = repo.create_candidate(profile)
        log_event(logger, "candidate.created", candidate_id=candidate_id)
        return CandidateCreateResponse(candidate_id=candidate_id, profile=profile)

    @app.post("/api/v1/matches", response_model=MatchesCreateResponse)
    def create_matches(payload: MatchesCreateRequest) -> MatchesCreateResponse:
        try:
            repo.get_candidate_profile(payload.candidate_id)
        except RuntimeError:
            raise HTTPException(status_code=404, detail="Candidate not found")
        jobs = [
            MatchCreateItem(job_id=repo.create_match_job(payload.candidate_id, jd_source), status="pending")
            for jd_source in payload.jd_sources
        ]
        for job in jobs:
            log_event(
                logger,
                "match.enqueued",
                job_id=job.job_id,
                candidate_id=payload.candidate_id,
                status=job.status,
            )
        log_event(logger, "matches.created", candidate_id=payload.candidate_id, count=len(jobs))
        return MatchesCreateResponse(jobs=jobs)

    @app.get("/api/v1/matches/{job_id}", response_model=MatchStatusResponse)
    def get_match(job_id: str) -> MatchStatusResponse:
        record = repo.get_match_result(job_id)
        if record is None:
            raise HTTPException(status_code=404, detail="Match job not found")
        agent_trace = None
        if record.agent_output is None:
            agent_trace = record.agent_trace
        return MatchStatusResponse(
            job_id=record.job_id,
            status=record.status,
            result=record.agent_output,
            agent_trace=agent_trace,
            error=record.last_error,
        )

    @app.get("/api/v1/matches", response_model=MatchListResponse)
    def list_matches(
        limit: int = Query(..., ge=1, le=100),
        offset: int = Query(..., ge=0),
        status: str | None = Query(None),
    ) -> MatchListResponse:
        items = repo.list_match_jobs(limit=limit, offset=offset, status=status)
        return MatchListResponse(
            items=[MatchListItem(job_id=item.job_id, status=item.status) for item in items],
            limit=limit,
            offset=offset,
        )

    @app.post("/api/v1/matches/{job_id}/requeue")
    def requeue_match(job_id: str) -> dict[str, str]:
        ok = repo.requeue_job(job_id)
        if not ok:
            raise HTTPException(status_code=404, detail="Match job not found")
        log_event(logger, "match.requeued", job_id=job_id)
        return {"job_id": job_id, "status": "pending"}

    return app
