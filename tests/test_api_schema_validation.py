import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from pelgo.api.app import create_app
from pelgo.api.schemas import MatchesCreateRequest


class _FakeRepo:
    def __init__(self, engine):
        self.engine = engine

    def create_candidate(self, profile_json):
        return "cand-1"


class _FakeSettings:
    database_url = "postgresql://test"
    llm_provider = None
    llm_api_key = None
    llm_model = None
    candidate_pdf_max_bytes = 10 * 1024 * 1024


def _build_client(monkeypatch: pytest.MonkeyPatch) -> TestClient:
    monkeypatch.setattr("pelgo.api.app.AppSettings", lambda: _FakeSettings())
    monkeypatch.setattr("pelgo.api.app.create_pg_engine", lambda database_url: object())
    monkeypatch.setattr("pelgo.api.app.PostgresJobRepository", _FakeRepo)
    monkeypatch.setattr("pelgo.api.app._extract_profile_with_llm", lambda resume_text, llm: (_ for _ in ()).throw(RuntimeError("llm unavailable")))
    return TestClient(create_app())


def test_candidate_endpoint_requires_exactly_one_resume_source(monkeypatch: pytest.MonkeyPatch) -> None:
    client = _build_client(monkeypatch)

    response = client.post("/api/v1/candidate")
    assert response.status_code == 400
    assert response.json()["detail"] == "Provide exactly one of resume_text or resume_pdf"

    response = client.post(
        "/api/v1/candidate",
        data={"resume_text": "cv text"},
        files={"resume_pdf": ("resume.pdf", b"fake", "application/pdf")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "Provide exactly one of resume_text or resume_pdf"


def test_candidate_endpoint_rejects_pdf_larger_than_configured_limit(monkeypatch: pytest.MonkeyPatch) -> None:
    class _SmallLimitSettings(_FakeSettings):
        candidate_pdf_max_bytes = 8

    monkeypatch.setattr("pelgo.api.app.AppSettings", lambda: _SmallLimitSettings())
    monkeypatch.setattr("pelgo.api.app.create_pg_engine", lambda database_url: object())
    monkeypatch.setattr("pelgo.api.app.PostgresJobRepository", _FakeRepo)
    client = TestClient(create_app())

    response = client.post(
        "/api/v1/candidate",
        files={"resume_pdf": ("resume.pdf", b"123456789", "application/pdf")},
    )
    assert response.status_code == 400
    assert response.json()["detail"] == "resume_pdf exceeds max size of 8 bytes"


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
