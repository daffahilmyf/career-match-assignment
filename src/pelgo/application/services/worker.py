from __future__ import annotations

import json
import time
from typing import Any

from pelgo.application.bootstrap.pii import build_pii_redactor
from pelgo.application.config import AppSettings
from pelgo.adapters.persistence.postgres_job_repository import PostgresJobRepository, create_pg_engine
from pelgo.application.bootstrap.llm import require_llm_client
from pelgo.application.logging import configure_logging, get_logger, log_event
from pelgo.application.orchestration.factory import run_agent
from pelgo.application.bootstrap.tools import build_tools
from pelgo.application.orchestration.state import AgentState
from pelgo.ports.persistence import JobRepositoryPort


RETRY_BACKOFF_SECONDS = [60, 300, 900]


def _sum_latency_ms(tool_calls: list[dict[str, Any]] | None) -> int:
    if not tool_calls:
        return 0
    return int(sum(call.get("latency_ms", 0) for call in tool_calls))


def run_worker_once(repo: JobRepositoryPort, settings: AppSettings, llm: Any, logger) -> bool:
    tools = build_tools(llm=llm, settings=settings)
    pii_redactor = build_pii_redactor()
    job = repo.claim_next_job()
    if job is None:
        return False

    log_event(logger, "job.claimed", job_id=job.id, candidate_id=job.candidate_id, status="processing")
    candidate_profile = repo.get_candidate_profile(job.candidate_id)
    sanitized_profile = pii_redactor.redact_profile(candidate_profile)
    state: AgentState = {
        "job_id": job.id,
        "candidate_profile": json.dumps(sanitized_profile),
        "job_input": job.jd_source,
    }
    final_state: AgentState | None = None
    try:
        log_event(logger, "candidate.context_sanitized", job_id=job.id, candidate_id=job.candidate_id, pii_redaction_applied=True)
        final_state = run_agent("langgraph", tools, state, settings, llm)
        result = final_state.get("result")
        if result is None:
            raise RuntimeError("Agent produced no result")
        output = result.model_dump(by_alias=True, mode="json")
        trace = output.get("agent_trace", {})
        tool_calls = trace.get("tool_calls")
        repo.mark_completed(job.id, output, trace)
        log_event(
            logger,
            "job.completed",
            job_id=job.id,
            status="completed",
            total_llm_calls=trace.get("total_llm_calls"),
            tool_calls=tool_calls,
            llm_latency_ms=_sum_latency_ms(tool_calls),
            llm_token_usage=getattr(llm, "usage")(),
        )
        return True
    except Exception as exc:
        attempt_index = min(job.attempts, len(RETRY_BACKOFF_SECONDS) - 1)
        retry_after = RETRY_BACKOFF_SECONDS[attempt_index]
        trace_source = final_state or state
        trace_payload = None
        if "trace_tool_calls" in trace_source:
            trace_payload = {
                "tool_calls": trace_source.get("trace_tool_calls", []),
                "total_llm_calls": trace_source.get("total_llm_calls", 0),
                "fallbacks_triggered": trace_source.get("fallbacks_triggered", 0),
            }
        repo.mark_failed(job.id, str(exc), job.attempts + 1, retry_after, trace_payload)
        log_event(
            logger,
            "job.failed",
            job_id=job.id,
            status="failed" if job.attempts + 1 >= 3 else "pending",
            error=str(exc),
            tool_calls=trace_payload.get("tool_calls") if trace_payload else None,
        )
        return True


def run_worker_loop(database_url: str) -> None:
    settings = AppSettings()
    engine = create_pg_engine(database_url)
    repo = PostgresJobRepository(engine)

    configure_logging()
    logger = get_logger("pelgo.worker")

    llm = require_llm_client(settings)

    while True:
        processed = run_worker_once(repo, settings, llm, logger)
        if not processed:
            time.sleep(settings.worker_poll_interval_seconds)
