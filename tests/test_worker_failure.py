from __future__ import annotations

from dataclasses import dataclass

from pelgo.application.config import AppSettings
from pelgo.application.services.worker import run_worker_once


@dataclass(frozen=True)
class FakeJob:
    id: str
    candidate_id: str
    jd_source: str
    attempts: int


class FakeRepo:
    def __init__(self) -> None:
        self.mark_failed_calls: list[dict[str, object]] = []

    def claim_next_job(self):
        return FakeJob(id="job-1", candidate_id="candidate-1", jd_source="JD text", attempts=2)

    def get_candidate_profile(self, candidate_id: str):
        return {
            "name": "Ari Pranata",
            "email": "ari@example.com",
            "skills": ["Python"],
            "years_experience": 6,
            "summary": "Ari Pranata can be reached at ari@example.com",
        }

    def mark_completed(self, job_id: str, output: dict, trace: dict) -> None:
        raise AssertionError("mark_completed should not be called on failure")

    def mark_failed(self, job_id: str, error: str, attempts: int, retry_after_seconds: int, trace: dict | None) -> None:
        self.mark_failed_calls.append(
            {
                "job_id": job_id,
                "error": error,
                "attempts": attempts,
                "retry_after_seconds": retry_after_seconds,
                "trace": trace,
            }
        )


class FakeLogger:
    def info(self, *args, **kwargs) -> None:
        return None


class FakeLLM:
    def usage(self):
        return None


def test_worker_failure_persists_partial_trace_and_final_failure_status(monkeypatch) -> None:
    repo = FakeRepo()
    settings = AppSettings()
    logger = FakeLogger()
    llm = FakeLLM()

    monkeypatch.setattr(
        "pelgo.application.services.worker.build_tools",
        lambda llm, settings: {"dummy": object()},
    )

    def fake_run_agent(provider, tools, initial_state, settings, llm):
        initial_state["trace_tool_calls"] = [
            {"tool": "extract_jd_requirements", "status": "success", "latency_ms": 10}
        ]
        initial_state["total_llm_calls"] = 2
        initial_state["fallbacks_triggered"] = 1
        raise RuntimeError("boom")

    monkeypatch.setattr("pelgo.application.services.worker.run_agent", fake_run_agent)

    processed = run_worker_once(repo, settings, llm, logger)

    assert processed is True
    assert len(repo.mark_failed_calls) == 1
    call = repo.mark_failed_calls[0]
    assert call["job_id"] == "job-1"
    assert call["attempts"] == 3
    assert call["retry_after_seconds"] == 900
    assert call["error"] == "boom"
    assert call["trace"] == {
        "tool_calls": [{"tool": "extract_jd_requirements", "status": "success", "latency_ms": 10}],
        "total_llm_calls": 2,
        "fallbacks_triggered": 1,
    }
