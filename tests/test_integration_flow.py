from __future__ import annotations

import os
import time

import pytest
from fastapi.testclient import TestClient

from pelgo.api.app import create_app
from pelgo.application.config import AppSettings
from pelgo.adapters.persistence.postgres_job_repository import PostgresJobRepository, create_pg_engine
from pelgo.application.bootstrap.llm import require_llm_client
from pelgo.application.logging import configure_logging, get_logger
from pelgo.application.services.worker import run_worker_once


@pytest.mark.integration
@pytest.mark.skipif(
    not os.getenv("DATABASE_URL") or not os.getenv("LLM_PROVIDER"),
    reason="DATABASE_URL and LLM_PROVIDER must be set for integration test",
)
def test_full_flow() -> None:
    settings = AppSettings()
    engine = create_pg_engine(settings.database_url or "")
    repo = PostgresJobRepository(engine)
    llm = require_llm_client(settings)

    configure_logging()
    logger = get_logger("pelgo.test")

    client = TestClient(create_app())

    candidate_payload = {"resume_text": "Jane Doe\nSkills: Python, PostgreSQL"}
    candidate_resp = client.post("/api/v1/candidate", data=candidate_payload)
    assert candidate_resp.status_code == 200
    candidate_id = candidate_resp.json()["candidate_id"]

    jd_text = "Backend Engineer\nRequirements: Python, PostgreSQL, AWS"
    match_resp = client.post("/api/v1/matches", json={"candidate_id": candidate_id, "jd_sources": [jd_text]})
    assert match_resp.status_code == 200
    job_id = match_resp.json()["jobs"][0]["job_id"]

    processed = run_worker_once(repo, settings, llm, logger)
    assert processed

    for _ in range(10):
        status_resp = client.get(f"/api/v1/matches/{job_id}")
        assert status_resp.status_code == 200
        payload = status_resp.json()
        if payload["status"] == "completed":
            assert payload["result"] is not None
            assert payload["result"]["agent_trace"]["tool_calls"]
            assert payload["result"]["reasoning"]
            return
        time.sleep(0.5)

    pytest.fail("Job did not complete in time")

