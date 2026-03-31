from __future__ import annotations

import io
import re
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, Query, UploadFile
from pydantic import BaseModel, ValidationError, field_validator, model_validator
from pypdf import PdfReader

from pelgo.adapters.persistence.postgres_job_repository import PostgresJobRepository, create_pg_engine
from pelgo.api.schemas import (
    CandidateCreateResponse,
    MatchCreateItem,
    MatchListItem,
    MatchListResponse,
    MatchesCreateRequest,
    MatchesCreateResponse,
    MatchStatusResponse,
)
from pelgo.application.bootstrap.llm import build_llm_client
from pelgo.application.config import AppSettings
from pelgo.application.logging import configure_logging, get_logger, log_event
from pelgo.domain.model.candidate_profile import CandidateProfile
from pelgo.prompts.templates import EXTRACT_CANDIDATE_PROFILE_PROMPT


class CandidateProfileExtraction(CandidateProfile):
    pass


class CandidateUploadInput(BaseModel):
    resume_text: str | None = None
    resume_pdf_bytes: int | None = None
    resume_pdf_content_type: str | None = None
    max_pdf_bytes: int = 10 * 1024 * 1024

    @field_validator("resume_text")
    @classmethod
    def _empty_text_to_none(cls, value: str | None) -> str | None:
        if value is not None and not value.strip():
            return None
        return value

    @model_validator(mode="after")
    def _validate_sources(self) -> "CandidateUploadInput":
        provided = [self.resume_text is not None, self.resume_pdf_bytes is not None]
        if sum(provided) != 1:
            raise ValueError("Provide exactly one of resume_text or resume_pdf")
        if self.resume_pdf_bytes is not None:
            if self.resume_pdf_bytes <= 0:
                raise ValueError("resume_pdf is empty")
            if self.resume_pdf_bytes > self.max_pdf_bytes:
                raise ValueError(f"resume_pdf exceeds max size of {self.max_pdf_bytes} bytes")
            if self.resume_pdf_content_type not in {"application/pdf", "application/octet-stream"}:
                raise ValueError("resume_pdf must be a PDF")
        return self


def _normalize_candidate_profile(profile: CandidateProfileExtraction) -> CandidateProfile:
    skills: list[str] = []
    seen: set[str] = set()
    for skill in profile.skills:
        cleaned = re.sub(r"[^a-z0-9+.#-]+", " ", skill.lower()).strip()
        if not cleaned or cleaned in seen:
            continue
        seen.add(cleaned)
        skills.append(cleaned)
    return CandidateProfile(
        name=profile.name.strip() if profile.name else None,
        email=profile.email.strip().lower() if profile.email else None,
        skills=skills,
        education=[item.strip() for item in profile.education if item and item.strip()],
        experience=[item.strip() for item in profile.experience if item and item.strip()],
        years_experience=max(0, int(profile.years_experience or 0)),
    )


def _extract_profile_from_text(resume_text: str) -> CandidateProfile:
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

    return CandidateProfile(
        name=name,
        email=email.lower() if email else None,
        skills=[skill.lower() for skill in skills],
        education=education,
        experience=experience_lines,
        years_experience=years_experience,
    )


def _extract_profile_with_llm(resume_text: str, llm: Any) -> CandidateProfile:
    prompt = EXTRACT_CANDIDATE_PROFILE_PROMPT.replace("{{resume_text}}", resume_text)
    extracted = llm.complete_json(prompt, CandidateProfileExtraction)
    return _normalize_candidate_profile(CandidateProfileExtraction.model_validate(extracted))


def _extract_text_from_pdf_bytes(pdf_bytes: bytes) -> str:
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
    llm = build_llm_client(settings)

    app = FastAPI(title="Pelgo Matching API", version="0.1.0")

    @app.get("/health")
    def health_check() -> dict[str, str]:
        return {"status": "ok"}

    @app.post("/api/v1/candidate", response_model=CandidateCreateResponse)
    async def create_candidate(
        resume_text: str | None = Form(None),
        resume_pdf: UploadFile | None = File(None),
    ) -> CandidateCreateResponse:
        pdf_bytes: bytes | None = None
        if resume_pdf is not None:
            pdf_bytes = await resume_pdf.read()
        try:
            CandidateUploadInput(
                resume_text=resume_text,
                resume_pdf_bytes=len(pdf_bytes) if pdf_bytes is not None else None,
                resume_pdf_content_type=resume_pdf.content_type if resume_pdf is not None else None,
                max_pdf_bytes=settings.candidate_pdf_max_bytes,
            )
        except ValidationError as exc:
            message = exc.errors()[0]["msg"]
            raise HTTPException(status_code=400, detail=message.removeprefix("Value error, ")) from exc

        final_resume_text = resume_text.strip() if resume_text is not None else _extract_text_from_pdf_bytes(pdf_bytes or b"")
        if not final_resume_text:
            raise HTTPException(status_code=400, detail="Resume text could not be extracted")
        try:
            profile = _extract_profile_with_llm(final_resume_text, llm)
        except Exception:
            profile = _extract_profile_from_text(final_resume_text)
        candidate_id = repo.create_candidate(profile.model_dump(mode="json"))
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
