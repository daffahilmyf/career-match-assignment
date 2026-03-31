from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient

from pelgo.api.app import create_app


@dataclass
class ApiTestSettings:
    database_url: str = "postgresql://test"
    llm_provider: str | None = None
    llm_api_key: str | None = None
    llm_model: str | None = None
    candidate_pdf_max_bytes: int = 10 * 1024 * 1024


class FakeCandidateRepo:
    def __init__(self, engine: object) -> None:
        self.engine = engine

    def create_candidate(self, profile_json: dict[str, Any]) -> str:
        return "cand-1"


@pytest.fixture
def api_client_factory(monkeypatch: pytest.MonkeyPatch) -> Callable[..., TestClient]:
    def _build(*, settings: ApiTestSettings | None = None, repo_factory: Any = FakeCandidateRepo) -> TestClient:
        active_settings = settings or ApiTestSettings()
        monkeypatch.setattr("pelgo.api.app.AppSettings", lambda: active_settings)
        monkeypatch.setattr("pelgo.api.app.create_pg_engine", lambda database_url: object())
        monkeypatch.setattr("pelgo.api.app.PostgresJobRepository", repo_factory)
        monkeypatch.setattr(
            "pelgo.api.app._extract_profile_with_llm",
            lambda resume_text, llm: (_ for _ in ()).throw(RuntimeError("llm unavailable")),
        )
        return TestClient(create_app())

    return _build
