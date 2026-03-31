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

1.
2.
3.

## Confidence heuristic

- TBD

## Agent Notes

- Tools:
- Failure handling:
- Termination condition:

## Ops

- Observability:
- Retry/dead-letter:

## Out of Scope

- Full GDPR/CCPA compliance or PII complience (beyond minimal data handling).
- Handling JD URLs that block scraping or require authentication/paywalls.
- Enterprise-grade fairness audits or bias tooling.
