from __future__ import annotations

import time
from textwrap import dedent
from typing import Any

import pytest
from fastapi.testclient import TestClient

from pelgo.api.app import create_app
from pelgo.application.config import AppSettings
from pelgo.adapters.persistence.postgres_job_repository import PostgresJobRepository, create_pg_engine
from pelgo.application.bootstrap.llm import require_llm_client
from pelgo.application.logging import configure_logging, get_logger
from pelgo.application.services.worker import run_worker_once


POLL_ATTEMPTS = 10
POLL_INTERVAL_SECONDS = 0.5
SAMPLE_RESUME = dedent(
    """
    John Doe
    AI Engineer
    Email: john.doe@example.com
    Phone: +1 415 555 0147
    Location: Seattle, WA
    LinkedIn: linkedin.com/in/johndoe-ai
    GitHub: github.com/johndoe-ai

    SUMMARY
    AI engineer with 6 years of experience building production machine learning and LLM-powered applications.
    Strong background in Python, FastAPI, retrieval systems, prompt orchestration, evaluation pipelines, and cloud infrastructure.
    Experienced in designing end-to-end AI workflows, deploying model-backed services, and improving reliability, observability, and product quality.

    SKILLS
    Python, FastAPI, PostgreSQL, Redis, Docker, AWS, LangChain, OpenAI API, vector databases, RAG, prompt engineering,
    LLM evaluation, CI/CD, Kubernetes, Terraform, feature engineering, ML pipelines, REST APIs, pytest, system design

    EXPERIENCE
    Senior AI Engineer | NovaLabs AI | 2022-2025
    - Built and maintained AI services for resume parsing, semantic search, and candidate-job matching across multiple enterprise customers.
    - Designed retrieval-augmented generation pipelines using embeddings, vector search, and prompt orchestration to improve answer quality and traceability.
    - Deployed FastAPI services backed by PostgreSQL, Redis, Docker, and AWS, supporting high-volume asynchronous processing workflows.
    - Created evaluation datasets, regression checks, and quality dashboards to monitor hallucination rates and tool-call behavior.

    Machine Learning Engineer | DataForge Systems | 2019-2022
    - Built NLP pipelines for document classification, information extraction, and ranking tasks using Python and cloud-managed infrastructure.
    - Implemented API integrations, batch processing jobs, and model monitoring for production ML systems.
    - Collaborated with product managers and backend engineers to turn research prototypes into customer-facing features.

    PROJECTS
    LLM Evaluation Platform
    - Developed an internal platform for prompt testing, response scoring, experiment tracking, and trace inspection.
    - Added reusable test fixtures and automated benchmarks for retrieval quality, latency, and structured output validation.

    EDUCATION
    B.Sc. Computer Science | University of Washington | 2019
    """
).strip()
SAMPLE_JD = dedent(
    """
    Senior AI Engineer | Applied Intelligence Platform

    Team Overview
    We build AI-powered workflow tools for talent intelligence, knowledge discovery, and enterprise automation.

    Requirements:
    - 5+ years of experience in software engineering, machine learning, or applied AI
    - Strong proficiency in Python and backend API development
    - Hands-on experience with LLM applications, prompt design, or retrieval-augmented generation
    - Solid understanding of PostgreSQL, data modeling, and asynchronous job processing
    - Experience with cloud infrastructure such as AWS and containerized deployment using Docker
    - Familiarity with evaluation frameworks, experimentation, and model quality measurement
    - Ability to ship production systems with strong observability, testing, and CI/CD practices

    Nice to Have:
    - Experience with vector databases and semantic search
    - Knowledge of LangChain, orchestration graphs, or agent-style workflows
    - Exposure to ranking systems, recommendation systems, or document intelligence

    Responsibilities:
    - Design and implement scalable AI services and matching pipelines
    - Build reliable APIs and worker systems for model-backed workflows
    - Improve prompt quality, evaluation coverage, and traceability across the platform
    - Partner with product and engineering teams to bring AI features into production
    """
).strip()


def _require_integration_settings() -> AppSettings:
    settings = AppSettings()
    if not settings.database_url or not settings.llm_provider or not settings.llm_api_key:
        pytest.skip("DATABASE_URL, LLM_PROVIDER, and LLM_API_KEY must be set for integration test")
    return settings


def _create_candidate(client: TestClient) -> str:
    response = client.post("/api/v1/candidate", data={"resume_text": SAMPLE_RESUME})

    assert response.status_code == 200
    payload = response.json()
    assert payload["candidate_id"]
    assert payload["profile"]["name"] == "John Doe"
    assert payload["profile"]["email"] == "john.doe@example.com"
    assert payload["profile"]["years_experience"] >= 6
    assert "python" in payload["profile"]["skills"]
    assert "postgresql" in payload["profile"]["skills"]
    assert "fastapi" in payload["profile"]["skills"]
    return payload["candidate_id"]


def _create_match_job(client: TestClient, candidate_id: str) -> str:
    response = client.post(
        "/api/v1/matches",
        json={"candidate_id": candidate_id, "jd_sources": [SAMPLE_JD]},
    )

    assert response.status_code == 200
    payload = response.json()
    assert len(payload["jobs"]) == 1
    assert payload["jobs"][0]["status"] == "pending"
    assert payload["jobs"][0]["job_id"]
    return payload["jobs"][0]["job_id"]


def _poll_completed_match(client: TestClient, job_id: str) -> dict[str, Any]:
    last_payload: dict[str, Any] | None = None

    for _ in range(POLL_ATTEMPTS):
        response = client.get(f"/api/v1/matches/{job_id}")
        assert response.status_code == 200
        payload = response.json()
        last_payload = payload

        if payload["status"] == "completed":
            return payload

        if payload["status"] == "failed":
            pytest.fail(f"Job failed: {payload['error']}")

        time.sleep(POLL_INTERVAL_SECONDS)

    pytest.fail(f"Job {job_id} did not complete in time; last payload: {last_payload}")


@pytest.mark.integration
def test_full_flow_creates_candidate_processes_match_and_returns_result() -> None:
    settings = _require_integration_settings()

    database_url = settings.database_url
    assert database_url is not None
    engine = create_pg_engine(database_url)
    repo = PostgresJobRepository(engine)
    llm = require_llm_client(settings)

    configure_logging()
    logger = get_logger("pelgo.test")
    client = TestClient(create_app())

    candidate_id = _create_candidate(client)
    job_id = _create_match_job(client, candidate_id)

    processed = run_worker_once(repo, settings, llm, logger)
    assert processed is True

    payload = _poll_completed_match(client, job_id)

    assert payload["job_id"] == job_id
    assert payload["status"] == "completed"
    assert payload["agent_trace"] is None

    result = payload["result"]
    assert result is not None
    assert result["job_id"] == job_id
    assert 0 <= result["overall_score"] <= 100
    assert result["reasoning"]
    assert isinstance(result["matched_skills"], list)
    assert isinstance(result["gap_skills"], list)
    assert result["agent_trace"]["tool_calls"]
