# System Design

## Overview

The system ingests a candidate profile and one or more job descriptions, runs an
agent to score fit and generate a learning plan, and stores the structured
results. An API and background workers coordinate the workflow so jobs run
asynchronously and can be queried by status.

## Known Information

- The system must score a candidate against one or more job descriptions and
  produce a structured learning plan.
- The agent output schema follows the Pelgo assignment documentation and must be
  validated JSON with an orchestrator-populated agent_trace.
- The API surface includes candidate ingestion, match submission, and match
  status/query endpoints.
- Agent runs are async jobs processed by out-of-process workers with safe job
  claiming and retries.
- The data store is PostgreSQL with structured candidate profiles and JSONB
  match outputs.

## Assumptions

- Fairness considerations are addressed as a best-effort internal quality goal,
  even though they are not explicitly required by the assignment.
- Candidate profile fields are limited to those needed for scoring (skills,
  experience, seniority signals) and can be expanded later.
- Shared caching of identical JD URLs across candidates is optional and can be
  deferred if it complicates correctness or isolation.
- Job description URLs are assumed to be publicly accessible job posting pages
  provided by the user (no guarantee of a specific provider).
- Prompt-injection guardrails are applied to external content (JD URLs and web
  resources) to prevent instructions from overriding system or tool policies,
  including malicious or bad-actor prompt injection.

**To answer ambiguity #1**

- Assumption: The agent follows a minimal sequence: extract requirements ->
  score candidate -> prioritize gaps -> only research top gaps.
- Reason: Keeps orchestration predictable and testable.
- Risk: May miss useful context.
- Mitigation: Allow an extra research step when confidence is low.

**To answer ambiguity #2**

- Assumption: The agent stops once it has a validated score, prioritized gaps,
  and resources for the top gaps, or after a bounded retry budget.
- Reason: Balances cost with completeness.
- Risk: Early stop on thin JDs.
- Mitigation: Low confidence triggers a retry or follow-up research.

**To answer ambiguity #3**

- Assumption: A tool is considered failed on timeout, schema validation error,
  or empty result.
- Reason: Failure modes are observable and actionable.
- Risk: False positives on partial data.
- Mitigation: Retry once and proceed with partial data if allowed by schema.

**To answer ambiguity #4**

- Assumption: If multiple jobs reference the same JD URL and the content has not
  drifted, the extracted requirements can be cached and reused. Drift is
  detected via a content hash or `Last-Modified` checks, with retention
  thresholds preferred over real-time checks to control cost.
- Reason: Improves performance for repeated JDs.
- Risk: Stale requirements.
- Mitigation: Refresh on hash change or age threshold.

**To answer ambiguity #5**

- Assumption: The profile focuses on recruiter-relevant fields I have seen in
  practice (Japan): skills, experience history, education/degree, and projects.
  Supplemental fields like location are included only when they influence
  eligibility (for example, visa constraints).
- Reason: Keeps the schema aligned with scoring signals.
- Risk: Missing niche signals.
- Mitigation: Allow schema extensions as new requirements appear.

## Core Functionality

- Should ingest a candidate resume (PDF or text), extract a structured profile,
  and store it in Postgres.
- Should accept up to 10 job descriptions per request (text or URL), enqueue one
  agent run per JD, and return job IDs immediately.
- Should run an agent that extracts requirements, scores candidate fit,
  prioritizes gaps, and builds a learning plan with real resources.
- Should persist the full structured agent output (including agent_trace) and
  expose status and results via API.

## Non-Functional Requirements

- Reliability: tool errors or timeouts must not crash workers, jobs retry and
  move to failed after max attempts. Measurement: a failing job retries up to 3
  times, then transitions to `failed` with error detail.
- Observability: structured logs for job ID, tool calls, status transitions, and
  LLM latency/tokens. Measurement: each job run emits log entries with `job_id`,
  `tool_calls`, `status_transition`, and `llm_latency_ms`.
- Correctness: agent outputs must be schema-validated before persistence.
  Measurement: invalid agent output never reaches the database; schema
  validation failure triggers retry or `failed`.
- Fairness (non-required): scoring should avoid obvious bias from protected
  attributes and focus on job-relevant skills and experience only. Measurement:
  inputs and outputs are reviewed to ensure protected attributes are excluded
  from scoring features.

## Stack

- Backend: Python API (FastAPI), Pydantic models.
- Orchestrator: Mentioned in reqs (but we can keep elaborate)
- Database: PostgreSQL with Alembic migrations.
- Queue/Workers: Out-of-process workers (implementation TBD).
- Frontend: Minimal web UI for upload, submit, and polling.

## Architecture

- API service
- Agent orchestrator
- Worker(s)
- Database

## Data Flow

1. `POST /api/v1/candidates` ingests a resume (PDF/text), extracts a structured
   profile, and stores it in Postgres. Returns `candidate_id`.
2. `POST /api/v1/matches` accepts up to 10 JDs (text or URL). Creates one
   `match_job` per JD, enqueues work, and returns `job_ids` in `pending`.
3. Workers claim jobs, load candidate + JD, run the agent, validate output, and
   persist JSONB `agent_output` + `agent_trace`.
4. `GET /api/v1/matches/{id}` returns job status and full structured output when
   `completed`, or error details when `failed`.

## Job State Machine

- States: `pending -> processing -> completed` or `failed`.
- Transitions:
  - `pending -> processing` on atomic claim.
  - `processing -> completed` on successful schema validation + persistence.
  - `processing -> pending` on retryable failure with backoff.
  - `processing -> failed` on max attempts or non-retryable errors.
- Job fields: `status`, `attempts`, `last_error`, `next_run_at`, `updated_at`.

## Queue/Worker Semantics

- Claiming: DB-backed job table with `SELECT ... FOR UPDATE SKIP LOCKED` to
  ensure race-safe claiming and allow 2+ concurrent workers.
- Concurrency: workers poll for `pending` jobs whose `next_run_at <= now()`.
- Idempotency: jobs are keyed by `job_id`; writes are conditional on job state.

## Retry and Failure Policy

- Max attempts: 3 total.
- Backoff: exponential (example: 1m, 5m, 15m) before retrying.
- Non-retryable: schema validation errors, prompt injection detection,
  unsupported JD formats, or missing required inputs.
- Failed jobs persist `last_error` and partial `agent_trace`.

## Data Model

- `candidates`: `id`, `created_at`, `profile_jsonb` (skills, experience,
  education, projects, optional location).
- `match_jobs`: `id`, `candidate_id`, `jd_source`, `status`, `attempts`,
  `next_run_at`, `last_error`, `created_at`, `updated_at`.
- `match_results`: `job_id`, `agent_output_jsonb`, `agent_trace_jsonb`,
  `completed_at`.
- Optional `jd_cache`: `jd_url`, `content_hash`, `requirements_jsonb`,
  `last_fetched_at`, `expires_at`.

## Confidence heuristic

- TBD

## Agent Notes

- Tools: JD fetcher (if URL), extraction tool, scoring, curated resource lookup.
- Failure handling: tool timeouts treated as retryable; validation failures are
  non-retryable.
- Termination condition: stop when score + gaps + resources are valid, or when
  retry budget is exhausted.

## Ops

- Observability: structured logs per `job_id` with tool calls, state transitions,
  latency, and token counts.
- Retry/dead-letter: 3 attempts max; failures remain queryable with errors.

## AI Safety Boundary

- Treat external JD content as untrusted input.
- Strip or ignore instructions inside scraped content.
- Disallow tool/system override and constrain tool usage to a whitelist.

## Resource/Cost Controls

- Per job caps on tokens, tool calls, and wall-clock timeouts.
- Hard stop when budget is exhausted; job fails with error detail.

## Governance Basics

- Store only job-relevant fields.
- Retention policy: delete candidate data after a fixed window (example: 30 days).
- Access logs for reads/writes; encryption at rest and TLS in transit.

## Implementation Process

1. Define schemas (Pydantic) and DB migrations for `candidates`, `match_jobs`,
   and `match_results`.
2. Implement `POST /candidates` and `POST /matches` with job creation + enqueue.
3. Build worker job claiming + execution loop with retries and validation.
4. Implement `GET /matches/{id}` with status and output payload.
5. Add observability (structured logs, basic metrics).
6. Add safety limits (timeouts, token budgets, tool whitelists).

## Out of Scope

- Full GDPR/CCPA compliance or PII complience (beyond minimal data handling).
- Handling JD URLs that block scraping or require authentication/paywalls.
- Enterprise-grade fairness audits or bias tooling.
