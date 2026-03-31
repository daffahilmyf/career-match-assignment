# System Design

## Overview

Pelgo ingests a candidate resume, stores a structured candidate profile in
PostgreSQL, accepts one or more job descriptions, and runs an LLM-driven agentic
matching pipeline asynchronously. The pipeline extracts JD requirements, scores
candidate fit, prioritizes skill gaps, researches learning resources, and stores
a validated structured result with an orchestrator-generated `agent_trace`.

The system is split into:
- a FastAPI API for ingestion and job submission
- a Postgres-backed async job queue
- out-of-process workers that execute the agent
- a LangGraph orchestrator with typed state and tool sequencing

## Implemented Scope

### Part A

Implemented:
- LangGraph-based orchestration with typed `AgentState`
- Four required tools:
  - `extract_jd_requirements`
  - `score_candidate_against_requirements`
  - `prioritise_skill_gaps`
  - `research_skill_resources`
- Structured final output per assignment schema
- Real `agent_trace` populated by orchestration/runtime state
- Failure handling for timeout, invalid tool output, and low-confidence flow

Not implemented:
- Google ADK stretch tool
- frontend as a scored deliverable; any UI is optional and out of scope for the core backend

### Part B

Implemented:
- `POST /api/v1/candidate`
- `POST /api/v1/matches`
- `GET /api/v1/matches/{id}`
- `GET /api/v1/matches`
- Postgres migrations and seed script
- out-of-process worker process
- race-safe job claiming using `FOR UPDATE SKIP LOCKED`
- retries with terminal failure after 3 attempts
- Docker Compose stack

Extra operational endpoints/features:
- `GET /health`
- `POST /api/v1/matches/{job_id}/requeue`
- structured worker and JD extraction logging
- lightweight candidate PII redaction before LLM execution

## Architecture

### Services

- `api`
  - FastAPI service in `src/pelgo/api/app.py`
  - validates input, stores candidates, enqueues match jobs, and returns status/results
- `worker`
  - background job runner in `src/pelgo/application/services/worker.py`
  - claims pending jobs and runs the LangGraph agent
- `postgres`
  - stores candidate profiles, match jobs, cached JD extractions, and final agent output

### Internal Layers

- `src/pelgo/domain/`
  - canonical output models and shared types
- `src/pelgo/application/orchestration/`
  - typed state, LangGraph routing, orchestration factory
- `src/pelgo/application/bootstrap/`
  - LLM, tool, and PII wiring
- `src/pelgo/adapters/tools/`
  - concrete tool implementations
- `src/pelgo/adapters/persistence/`
  - Postgres repository
- `src/pelgo/ports/`
  - persistence, LLM, PII, and tooling ports

## API Contract

### `POST /api/v1/candidate`

Purpose:
- ingest a candidate resume and store a structured candidate profile

Current input contract:
- multipart form data
- exactly one of:
  - `resume_text`
  - `resume_pdf`

Behavior:
- PDF text is extracted with `pypdf`
- candidate profile extraction is LLM-first
- if LLM extraction fails, a heuristic parser is used as fallback
- stored profile is structured JSON, not a raw blob

Current candidate profile fields:
- `name`
- `email`
- `skills`
- `education`
- `experience`
- `years_experience`

### `POST /api/v1/matches`

Purpose:
- accept up to 10 JDs for an existing candidate and enqueue one job per JD

Input:
- `candidate_id`
- `jd_sources[]`

JD source types supported:
- raw JD text
- JD URL

Response:
- immediate list of `job_id` values with `pending` status

### `GET /api/v1/matches/{id}`

Purpose:
- fetch one job’s status and final structured output

Status values:
- `pending`
- `processing`
- `completed`
- `failed`

Response behavior:
- completed jobs expose final result in `result`
- failed jobs expose top-level `agent_trace` if no final result exists

### `GET /api/v1/matches`

Purpose:
- paginated list of jobs with optional status filter

Required query params:
- `limit`
- `offset`

## Data Flow

1. Candidate resume is submitted to `POST /api/v1/candidate`.
2. API extracts or reads resume text, builds a structured candidate profile, and stores it.
3. Client submits up to 10 JD sources to `POST /api/v1/matches`.
4. API creates one `match_job` row per JD source with status `pending`.
5. Worker claims a pending job atomically.
6. Worker sanitizes candidate context and executes the LangGraph agent.
7. Agent runs tools at runtime, builds a validated final result, and persists it.
8. Client polls `GET /api/v1/matches/{id}` for status and final output.

## Orchestration Design

Primary orchestrator:
- LangGraph

Typed state:
- `AgentState` managed by LangGraph

Core flow:
1. extract JD requirements
2. score candidate against requirements
3. if gaps exist, prioritize them
4. if confidence is low or resources are still needed, research a bounded subset of gaps
5. assemble final result

### Runtime sequencing

The sequence is not hardcoded as a single fixed linear run. The graph routes based
on current state:
- missing requirements -> extract requirements
- missing score -> score candidate
- low confidence with gaps -> prioritize + research
- no remaining researchable gaps -> assemble result

### Termination condition

The graph assembles a result when:
- requirements and score exist
- no further bounded research is needed, or
- research is exhausted/time-capped, or
- confidence and gathered evidence are sufficient

## Tool Design

### `extract_jd_requirements`

Input:
- raw JD text or URL

Output:
- `required_skills`
- `nice_to_have_skills`
- `seniority_level`
- `domain`
- `responsibilities`

Current behavior:
- raw text: sent directly to the LLM extractor
- URL: fetched with `requests`, cleaned, then sent to the LLM extractor
- URL outputs are cached in `jd_cache`
- output is schema-validated before use

Failure behavior:
- malformed output: retried, then treated as failure
- URL timeout: treated as explicit JD URL failure
- blocked URL (e.g. HTTP 403): treated as explicit JD URL failure
- raw-text extraction failure: can fall back to empty/default requirements
- URL extraction failure does not silently produce an empty successful result

Current limitation:
- JS-rendered or bot-protected job pages may fail

### `score_candidate_against_requirements`

Output:
- `overall_score`
- `dimension_scores`
- `matched_skills`
- `gap_skills`
- `confidence`

Confidence heuristic is derived from observable signals:
- JD completeness
- required skill coverage
- experience alignment
- seniority alignment
- domain overlap

### `prioritise_skill_gaps`

Output:
- ranked skill gaps with:
  - `skill`
  - `priority_rank`
  - `estimated_match_gain_pct`
  - `rationale`

Behavior:
- LLM-first ranking
- heuristic fallback if the LLM path fails
- includes every gap exactly once

### `research_skill_resources`

Output:
- resources with:
  - `title`
  - `url`
  - `estimated_hours`
  - `type`
- `relevance_score`

Behavior:
- makes real external calls
- uses MIT OpenCourseWare API and web lookup/reranking
- URL/title/body heuristics rerank candidate resources
- resources are bounded by configured top-gap and time limits

Current limitation:
- resource quality is still heuristic and uneven for some practical skills

## Failure Handling

Implemented failure modes:

### Tool timeout

- tool call wrapper records failure in trace
- timeout can trigger retry or fallback depending on the node
- research timeout falls back to a search resource rather than crashing the job

### Invalid tool output

- output is schema-validated after tool execution
- malformed output is treated as a failed tool call
- retries/fallbacks depend on the node and input type

### Low confidence score

- low confidence does not silently terminate
- low confidence triggers gap prioritization and targeted resource research before final assembly

### Final worker failure policy

- max attempts: 3
- backoff schedule:
  - 60s
  - 300s
  - 900s
- after the 3rd failure, the job moves to `failed`
- partial `agent_trace` is persisted with the error

## Job State Machine

States:
- `pending`
- `processing`
- `completed`
- `failed`

Transitions:
- `pending -> processing` on atomic claim
- `processing -> completed` on validated result persistence
- `processing -> pending` on retryable failure before max attempts
- `processing -> failed` after 3 attempts

Current dead-letter interpretation:
- terminal failed jobs remain in the same Postgres table with error detail and trace
- this is a terminal failed state, not a separate DLQ table or broker queue

## Queue and Worker Semantics

Queue implementation:
- Postgres-backed job table

Claiming:
- `SELECT ... FOR UPDATE SKIP LOCKED`

Concurrency:
- 2+ workers can process concurrently without duplicate claims

Observability:
- worker logs include:
  - `worker.started`
  - `worker.idle`
  - `job.claimed`
  - `job.completed`
  - `job.failed`
- logs include worker host/pid, job IDs, tool calls, LLM latency, and token usage

## Data Model

### `candidates`
- candidate ID
- structured profile JSON
- timestamps

### `match_jobs`
- job ID
- candidate ID
- original JD source
- status
- attempts
- next run time
- last error
- agent output JSON
- agent trace JSON
- timestamps

### `jd_cache`
- JD URL
- content hash
- structured extracted requirements
- timestamps

Query support:
- all jobs for a candidate
- jobs by status
- trace/output for a specific job

## Privacy and Safety

### Candidate context

Before candidate data is sent to the LLM:
- direct PII is sanitized with a lightweight redactor
- structured matching-relevant fields remain available

This is a pragmatic privacy guardrail, not full compliance-grade PII handling.

### External content

JD URL content and web resource content are treated as untrusted input.
The system does not allow external content to override tool or orchestration logic.

## Configuration

Current key settings:
- `DATABASE_URL`
- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_MODEL`
- `TOP_GAP_LIMIT`
- `RESEARCH_TIME_CAP_SECONDS`
- `MIT_COURSE_LIMIT`
- `WORKER_POLL_INTERVAL_SECONDS`
- `CANDIDATE_PDF_MAX_BYTES`

## Docker / Local Run

Current Compose model:
- `db`
- `api`
- `worker`
- `migrate`

Workers can be scaled with:
```bash
docker compose up --build --scale worker=2
```

This is the intended way to verify concurrent out-of-process processing.

## Testing Status

Implemented coverage includes:
- API validation
- candidate profile extraction normalization
- LangGraph routing and failure behavior
- match status response shape
- PII redaction
- resource selection
- worker partial-trace persistence on failure
- JD URL extraction path

There is also an integration test for the full lifecycle, but it is environment-gated.

## Current Limitations

- README and submission documentation may lag behind the code if not updated together.
- JD URL extraction still fails on blocked or JS-heavy sites.
- candidate `years_experience` is improved on the LLM path, but heuristic fallback remains conservative and simple.
- resource relevance is still heuristic for some applied tooling skills.
- there is no separate broker or external DLQ; Postgres is both source of truth and job queue.

## Future Work

- tighten heuristic fallback parsing for candidate experience
- improve JD page extraction with a more robust text extraction pipeline
- make resource reranking more semantic and less lexical
- add a dedicated DLQ table for terminal failures
- optionally add a broker/event stream such as NATS JetStream for higher-throughput future architectures while keeping Postgres as the source of truth
