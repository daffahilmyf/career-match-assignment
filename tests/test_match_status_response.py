from __future__ import annotations

from types import SimpleNamespace

from fastapi.testclient import TestClient

from pelgo.api.app import create_app


class _FakeRepo:
    def __init__(self, engine: object, record: SimpleNamespace) -> None:
        self.engine = engine
        self._record = record

    def get_match_result(self, job_id: str):
        return self._record


def test_get_match_hides_top_level_agent_trace_when_result_exists(monkeypatch) -> None:
    record = SimpleNamespace(
        job_id="job-1",
        status="completed",
        agent_output={
            "job_id": "job-1",
            "overall_score": 90,
            "confidence": "high",
            "dimension_scores": {"skills": 90, "experience": 90, "seniority_fit": 90},
            "matched_skills": ["python"],
            "gap_skills": [],
            "reasoning": "good fit",
            "learning_plan": [],
            "agent_trace": {"tool_calls": [{"tool": "extract_jd_requirements", "status": "success", "latency_ms": 10}], "total_llm_calls": 2, "fallbacks_triggered": 0},
        },
        agent_trace={"tool_calls": [{"tool": "extract_jd_requirements", "status": "success", "latency_ms": 10}]},
        last_error=None,
    )

    monkeypatch.setattr("pelgo.api.app.AppSettings", lambda: SimpleNamespace(database_url="postgresql://test"))
    monkeypatch.setattr("pelgo.api.app.create_pg_engine", lambda database_url: object())
    monkeypatch.setattr("pelgo.api.app.PostgresJobRepository", lambda engine: _FakeRepo(engine, record))

    client = TestClient(create_app())
    response = client.get("/api/v1/matches/job-1")

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["agent_trace"]["tool_calls"]
    assert payload["agent_trace"] is None


def test_get_match_exposes_top_level_agent_trace_when_result_missing(monkeypatch) -> None:
    record = SimpleNamespace(
        job_id="job-2",
        status="failed",
        agent_output=None,
        agent_trace={"tool_calls": [{"tool": "extract_jd_requirements", "status": "failed", "latency_ms": 10}], "total_llm_calls": 1, "fallbacks_triggered": 1},
        last_error="tool failed",
    )

    monkeypatch.setattr("pelgo.api.app.AppSettings", lambda: SimpleNamespace(database_url="postgresql://test"))
    monkeypatch.setattr("pelgo.api.app.create_pg_engine", lambda database_url: object())
    monkeypatch.setattr("pelgo.api.app.PostgresJobRepository", lambda engine: _FakeRepo(engine, record))

    client = TestClient(create_app())
    response = client.get("/api/v1/matches/job-2")

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"] is None
    assert payload["agent_trace"]["tool_calls"][0]["tool"] == "extract_jd_requirements"
    assert payload["error"] == "tool failed"
