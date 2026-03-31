import pytest
from pydantic import ValidationError

from pelgo.api.schemas import CandidateCreateRequest, MatchesCreateRequest


def test_candidate_request_requires_exactly_one_resume_source() -> None:
    with pytest.raises(ValidationError):
        CandidateCreateRequest()

    with pytest.raises(ValidationError):
        CandidateCreateRequest(resume_text="cv text", resume_pdf_base64="ZmFrZQ==")

    payload = CandidateCreateRequest(resume_text="cv text")
    assert payload.resume_text == "cv text"
    assert payload.resume_pdf_base64 is None


def test_matches_request_strips_and_validates_jd_sources() -> None:
    payload = MatchesCreateRequest(
        candidate_id="cand-1",
        jd_sources=["  https://example.com/job  ", "Backend engineer\nRequirements: Python"],
    )

    assert payload.jd_sources == [
        "https://example.com/job",
        "Backend engineer\nRequirements: Python",
    ]

    with pytest.raises(ValidationError):
        MatchesCreateRequest(candidate_id="cand-1", jd_sources=["   "])
