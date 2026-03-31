# Pelgo AI Lead Assignment

[![CI](https://github.com/daffahilmyf/career-match-assignment/actions/workflows/ci.yml/badge.svg)](https://github.com/daffahilmyf/career-match-assignment/actions/workflows/ci.yml)

## Executive Summary

This project implements an asynchronous, agent-driven job-matching pipeline for
Pelgo.

At a high level:

- a candidate submits a resume
- the system stores a structured candidate profile in PostgreSQL
- one or more job descriptions are submitted as text or URL
- a background worker runs an agentic evaluation per job description
- the system returns a structured match result and a practical learning plan

The design deliberately prioritizes **Part A depth** over unnecessary
infrastructure complexity. The core of the submission is a LangGraph-based agent
with typed state, runtime tool sequencing, schema-validated outputs, and a real
runtime-generated `agent_trace`.

## 5-Minute Quick Start

If you want to get the system running as quickly as possible:

1. Copy the example env file:

```bash
cp .env.example .env
```

2. Fill in at least these values in `.env`:

- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_MODEL`

3. Start the full stack:

```bash
docker compose up --build
```

This Compose flow already brings up the database, runs migrations, and includes
the seeded setup expected for local review.

4. Open the API docs:

- `http://localhost:8000/docs`

If you want to test concurrent workers:

```bash
docker compose up --build --scale worker=2
```

If Docker is not your preferred path, local run instructions are included later
in this README.

## What Is Implemented

### Part A: Agentic Career Intelligence

Implemented:

- LangGraph orchestrator with typed `AgentState`
- required four-tool suite
- runtime tool sequencing
- bounded planning/research policy
- structured final output per assignment schema
- runtime-owned `agent_trace`
- explicit handling for timeout, invalid tool output, and low-confidence cases

Tool suite:

- `extract_jd_requirements(job_url_or_text)`
- `score_candidate_against_requirements(candidate_profile, requirements)`
- `prioritise_skill_gaps(gap_skills, job_market_context)`
- `research_skill_resources(skill_name, seniority_context)`

### Part B: Async Infrastructure

Implemented:

- `POST /api/v1/candidate`
- `POST /api/v1/matches`
- `GET /api/v1/matches/{id}`
- `GET /api/v1/matches`
- PostgreSQL schema and Alembic migrations
- seed script
- out-of-process worker process
- race-safe job claiming with `FOR UPDATE SKIP LOCKED`
- retry handling with terminal failure after 3 attempts
- Docker Compose stack

Operational extras:

- `GET /health`
- `POST /api/v1/matches/{job_id}/requeue`
- structured JSON logging
- lightweight PII redaction before LLM execution

## Further Reading

Additional design notes are available in `docs/`:

- `docs/system-design.md` — system structure, data flow, storage model, queue
  model, and current limitations
- `docs/orchestration-decisions.md` — orchestration choices, trade-offs, failure
  handling, and scaling paths

## Framework Choice

I chose **LangGraph** because it gave me explicit typed state, controlled
runtime sequencing, and orchestration-owned trace data without forcing a large
custom agent loop.

## System in One Pass

1. Candidate resume is submitted as text or PDF.
2. The API extracts and stores a structured candidate profile.
3. Up to 10 job descriptions are submitted in one request.
4. The API creates one background job per JD and returns immediately.
5. Workers claim jobs from PostgreSQL and run the agent.
6. The agent extracts requirements, scores fit, prioritizes gaps, and researches
   learning resources.
7. The final result is schema-validated and stored with its `agent_trace`.
8. Clients poll the job endpoint for status and final output.

## Assumptions and Deliberate Extensions

A few choices go slightly beyond the minimum assignment scope because they
improve the quality of the system or clarify ambiguous parts of the spec.

### Assumptions

- **JD URLs are public pages**: if a site blocks scraping or depends on heavy
  browser rendering, the run fails explicitly rather than pretending extraction
  succeeded.
- **Candidate profile is intentionally compact**: I stored the fields needed for
  matching quality now — skills, experience, education, and experience-level
  signals — instead of trying to design a full recruiting schema upfront.
- **JD caching is worth it**: repeated JD URL extraction is cached because it
  reduces repeated work and keeps the main agent path cheaper.
- **Confidence should be evidence-based**: I treated confidence as a runtime
  heuristic from measurable signals rather than a model self-report.

### Extensions beyond the minimum

- **PII boundary before LLM execution**: candidate context is lightly sanitized
  before it reaches the agent. This is not compliance-grade privacy engineering,
  but it reduces unnecessary exposure.
- **Fairness-aware boundary**: the same input boundary also reduces the chance
  that irrelevant personal details influence the model’s reasoning.
- **Runtime-owned trace**: `agent_trace` is generated by the
  orchestration/runtime layer rather than by the model.
- **Operational helpers**: health, requeue, and structured logs were added
  because they make the async system easier to inspect and operate.
- **Future scaling paths were considered early**: the current system
  intentionally stays simple with Postgres as both source of truth and queue,
  while leaving a clean path to broker-based or crawler-heavier alternatives
  later if scale demands it.

## API Surface

| Endpoint                   | Purpose                                                                            | Input                                                                          | Output                                                                             |
| -------------------------- | ---------------------------------------------------------------------------------- | ------------------------------------------------------------------------------ | ---------------------------------------------------------------------------------- |
| `POST /api/v1/candidate`   | Ingest a candidate resume and store a structured profile                           | Multipart form data. Exactly one of `resume_text` or `resume_pdf`.             | `candidate_id` and the structured candidate profile.                               |
| `POST /api/v1/matches`     | Accept up to 10 job descriptions for a stored candidate and enqueue one job per JD | `candidate_id` and up to 10 `jd_sources[]` values. Each JD can be text or URL. | List of `job_id` values with initial `pending` status.                             |
| `GET /api/v1/matches/{id}` | Return one job’s status and structured result                                      | Path parameter `id`                                                            | Job status plus final result when completed, or error / partial trace when failed. |
| `GET /api/v1/matches`      | Return a paginated list of jobs with optional status filtering                     | `limit`, `offset`, optional `status`                                           | Paginated job list.                                                                |

## Confidence Heuristic

Confidence is derived from observable signals rather than model self-report.

| Signal               | What it measures                                                                | Weight |
| -------------------- | ------------------------------------------------------------------------------- | ------ |
| JD completeness      | Whether the job description contains enough structured signal to score reliably | `0.20` |
| Skill coverage       | Ratio of matched required skills to total required skills                       | `0.35` |
| Experience alignment | Whether the candidate’s experience level matches the role expectation           | `0.25` |
| Seniority alignment  | Whether candidate seniority fits the JD seniority level                         | `0.10` |
| Domain overlap       | Whether the candidate background overlaps with the job domain                   | `0.10` |

Thresholds:

- `high >= 0.75`
- `medium >= 0.50 and < 0.75`
- `low < 0.50`

Reasoning behind this heuristic:

| Signal               | Why it is included                                                                                 |
| -------------------- | -------------------------------------------------------------------------------------------------- |
| JD completeness      | A thin or ambiguous JD should lower confidence even if other signals look strong.                  |
| Skill coverage       | This is the strongest direct signal of fit, so it carries the most weight.                         |
| Experience alignment | Skills alone can overstate fit if the candidate has not operated at the expected level yet.        |
| Seniority alignment  | Useful, but less informative than concrete skill and experience evidence, so it is weighted lower. |
| Domain overlap       | Helps distinguish roles that look similar on paper but differ in actual operating context.         |

I chose this heuristic because it is observable, explainable, and easy to tune
later. It is more trustworthy for this assignment than model self-reported
confidence, and much lighter-weight than a fully benchmark-calibrated confidence
model.

## Failure-Mode Decisions

The assignment explicitly asks for three failure modes to be handled. I treated
those as orchestration decisions, not just error cases, because the important
question is not only whether the system notices the failure, but how it chooses
to proceed.

| Failure mode        | Typical trigger                                                     | Current behavior                                                                                                                              | Why this choice                                                                                        |
| ------------------- | ------------------------------------------------------------------- | --------------------------------------------------------------------------------------------------------------------------------------------- | ------------------------------------------------------------------------------------------------------ |
| Tool timeout        | External fetch or research step takes too long                      | Record failure in `agent_trace`, retry when appropriate, use fallback behavior where a degraded result is still useful, keep the worker alive | Prevents one slow tool from crashing the run while still preserving a useful output path               |
| Invalid tool output | Tool returns malformed structured data that fails schema validation | Reject the output immediately, record the failure, then retry or fail depending on the node and input type                                    | Keeps bad structured data out of the pipeline and prevents malformed outputs from reaching persistence |
| Low confidence      | Score is computed successfully but evidence is weak                 | Do not finalize immediately; require gap prioritization and targeted follow-up research before assembling the final result                    | Low confidence should lead to more evidence gathering, not a silent weak answer                        |

### 1. Tool timeout

| Item                   | Decision                                                                                                                          |
| ---------------------- | --------------------------------------------------------------------------------------------------------------------------------- |
| What counts as timeout | A tool call exceeding its practical threshold, especially on external calls                                                       |
| What the system does   | Records the failed call in trace, increments fallback count, retries if the step is retryable, and keeps the worker process alive |
| Fallback path          | For resource lookup, the system can fall back to a search resource rather than failing the entire run                             |
| Why this is reasonable | Timeout is often temporary or source-related, so the system should degrade gracefully before treating it as terminal              |

### 2. Invalid tool output

| Item                          | Decision                                                                                                                         |
| ----------------------------- | -------------------------------------------------------------------------------------------------------------------------------- |
| What counts as invalid output | Any tool response that fails schema validation                                                                                   |
| What the system does          | Rejects it immediately, records the failure, and either retries or fails explicitly depending on the node                        |
| Strongest example             | Malformed JD extraction for a JD URL becomes an explicit extraction failure rather than a weak fake success                      |
| Why this is reasonable        | Schema failures are correctness failures, so they should be surfaced early instead of being normalized into downstream ambiguity |

### 3. Low confidence

| Item                          | Decision                                                                                                                      |
| ----------------------------- | ----------------------------------------------------------------------------------------------------------------------------- |
| What counts as low confidence | Confidence score below the configured threshold after scoring                                                                 |
| What the system does          | Does not silently assemble the final result; instead it prioritizes gaps and performs bounded follow-up research              |
| Stop condition                | Once the bounded research path is complete or exhausted, the graph assembles the final output                                 |
| Why this is reasonable        | A low-confidence score should trigger additional evidence gathering rather than being returned as if it were already complete |

## Main Trade-offs

| Decision                                               | Why I chose it                                                                                                                                                                                                                                                                                                                                                             | Trade-off accepted                                                                                                                                         |
| ------------------------------------------------------ | -------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------------------------------------------- |
| LangGraph over Google ADK                              | Google ADK was a credible alternative, but LangGraph fit this codebase better. It gave me explicit state, runtime routing, and trace control with a smaller and more predictable integration surface.                                                                                                                                                                      | I gave up a stronger ADK-native session/event model in exchange for a simpler primary orchestration stack.                                                 |
| PostgreSQL queue over an external broker               | PostgreSQL is durable, simple, and fully sufficient for the assignment. It also keeps local setup and debugging straightforward.                                                                                                                                                                                                                                           | I accepted a polling-based worker model instead of introducing a broker on day one.                                                                        |
| Lightweight retrieval over a crawler-heavy stack       | I kept JD and resource retrieval simple so more time went into the matching agent itself. For learning resources, I prefer targeted sources first (for example MIT OpenCourseWare) because they are more stable and easier to reason about than general web search. DuckDuckGo is used as a fallback when the preferred source path does not return enough usable results. | Some sites are not reliably crawlable, especially blocked, anti-bot, or JS-heavy pages, and fallback search is less reliable than a curated provider path. |
| LLM-first candidate extraction with heuristic fallback | This gives stronger candidate profiles in the common path while keeping ingestion resilient if the LLM path fails.                                                                                                                                                                                                                                                         | The fallback parser remains simpler and less accurate than the LLM path.                                                                                   |
| Lightweight privacy boundary                           | PII redaction improves privacy and keeps the model focused on job-relevant information without adding a large compliance-heavy subsystem.                                                                                                                                                                                                                                  | This is a practical safeguard, not a full compliance-grade privacy system.                                                                                 |

### Future scaling paths

These are the main upgrades I would consider next, depending on both product
pressure and technical constraints.

| Area                                  | When it becomes worth doing                                                                 | Business driver                                                             | Technical driver                                                                   | Likely direction                                                                                                       |
| ------------------------------------- | ------------------------------------------------------------------------------------------- | --------------------------------------------------------------------------- | ---------------------------------------------------------------------------------- | ---------------------------------------------------------------------------------------------------------------------- |
| Queue / broker                        | When worker throughput, event fan-out, or latency starts to outgrow simple Postgres polling | More concurrent jobs, faster status updates, cleaner event-driven workflows | Polling overhead, more worker services, need for stronger delivery semantics       | `NATS JetStream`, `RabbitMQ`, or `Kafka` depending on latency vs throughput vs retention needs                         |
| JD extraction / crawling              | When blocked sites and inconsistent job pages become a meaningful share of traffic          | More real-world JD coverage, fewer failed URL submissions                   | Anti-bot pages, JS-heavy sites, inconsistent HTML, need for stronger extraction    | Dedicated crawler/extractor layer with browser or stealth support where needed                                         |
| Resource discovery                    | When learning-plan quality becomes more important than minimal retrieval cost               | Better recommendations and stronger user trust in learning plans            | Better page extraction, stronger reranking, broader source coverage                | Richer retrieval/reranking pipeline and possibly curated source classes                                                |
| Provider locking for learning content | When consistency and quality matter more than broad discovery                               | More predictable resource quality and stronger user trust                   | Less noisy retrieval, fewer irrelevant search results, clearer provider contracts  | Prefer a locked provider set such as MIT OCW, Coursera, or other curated sources before falling back to broader search |
| Candidate parsing                     | When resume quality and ingestion accuracy start limiting score quality                     | Better profile quality, fewer bad extractions, stronger reviewer trust      | More varied resume formats, weak heuristic fallback, need for richer normalization | Stronger extraction logic and tighter fallback parsing                                                                 |
| Failure handling / DLQ                | When failed-job volume grows and manual requeue becomes noisy                               | Cleaner operations and easier support workflows                             | Better separation between active jobs and terminal failures                        | Dedicated DLQ table or broker-backed dead-letter path                                                                  |

The pattern is the same across these areas: I kept the current system simple
where it was enough for the assignment, but the next upgrades are already clear
if business needs or runtime complexity increase.

## Known Limitations

- Some JD URLs cannot be fetched because the remote site blocks scraping.
- JS-heavy job pages are not fully supported.
- Resource relevance is still heuristic for some practical skills.
- `years_experience` is stronger on the LLM extraction path than on the fallback
  parser.
- Failed jobs remain in the main jobs table rather than a dedicated DLQ table.

## Final Prompt Set

### Planner prompt

```text
You are orchestrating tools for a job match pipeline. Pick the single best next step.
Available tools: extract_jd_requirements, score_candidate_against_requirements, prioritise_skill_gaps, research_skill_resources.
Return JSON that matches this schema exactly:
{
  "next_step": "extract_jd_requirements | score_candidate_against_requirements | prioritise_skill_gaps | research_skill_resources | assemble_result | null",
  "should_stop": true | false
}

Rules:
- Choose exactly one next step.
- Use assemble_result only when enough evidence has been gathered.
- If confidence is low, do not stop until you have prioritised gaps and attempted targeted research.
- Respect dependencies: scoring requires extracted requirements; research requires prioritised gaps.
```

### JD extraction prompt

```text
You are a senior recruiter and talent intelligence analyst. Your task is to extract structured job requirements from the job description.

Return JSON that matches this schema exactly:
- required_skills: list of canonical skill tokens (e.g., "python", "aws", "project management")
- nice_to_have_skills: list of canonical skill tokens
- seniority_level: one of intern|junior|mid|senior|lead|staff|principal|unspecified
- domain: short domain label (e.g., "backend", "data", "sales", "operations")
- responsibilities: list of short responsibility phrases

Rules:
- Only include concrete skills, tools, or domain-specific capabilities in skill lists.
- Exclude years of experience, role titles, soft skills, or full requirement sentences.
- Normalize skills to lowercase and use canonical names.
- Responsibilities should be concise, verb-led phrases (3-10 words).
```

### Gap prioritization prompt

```text
You are prioritising missing skills to close a job match gap.
Job context:
{{job_context}}

Gap skills:
{{gap_list}}

Return JSON that matches this schema exactly:
{
  "ranked_skills": [
    {"skill": "string", "priority_rank": int, "estimated_match_gain_pct": int, "rationale": "string"}
  ]
}

Rules:
- Include every gap skill exactly once.
- priority_rank starts at 1 with no gaps.
- estimated_match_gain_pct must be 5-20.
- rationale must be specific to the job context (not generic).
```

### Resource hour estimation prompt

```text
You are estimating learning time for a list of resources.

Return JSON that matches this schema exactly:
{ "hours": [int, int, ...] }

Rules:
- Provide one integer per resource, in the same order.
- Each value must be between 2 and 40 hours.
- If unsure, pick a reasonable default based on title/type.
```

### Match reasoning prompt

```text
Write a 2-3 sentence reasoning summary for the match score. Use the candidate profile and the job description as context. Mention matched skills and key gaps in plain English. Keep it concise and avoid bullet points.
```

### Candidate profile extraction prompt

```text
You are extracting a structured candidate profile from a resume.

Return JSON that matches this schema exactly:
- name: string | null
- email: string | null
- skills: list of canonical skill tokens
- education: list of concise education entries
- experience: list of concise work experience entries
- years_experience: integer >= 0

Rules:
- Normalize skills to lowercase canonical names.
- Keep education and experience entries short and factual.
- If a field is missing, use null for scalar fields and [] for list fields.
- years_experience must be conservative and evidence-based.
- Only use years_experience when the resume explicitly states a total like "5 years of experience"
  or when work date ranges clearly support a conservative total.
- Do not infer years_experience from seniority titles alone.
- Do not use graduation dates, project durations, or unrelated year mentions.
- If the total years of experience is ambiguous, return 0.
```

## Running the Project

### Docker Compose

This is the default path for reviewers. Docker Compose brings up Postgres, API,
and worker services together.

1. Copy the env file:

```bash
cp .env.example .env
```

2. Fill in at least:

- `LLM_PROVIDER`
- `LLM_API_KEY`
- `LLM_MODEL`

3. Start the full stack:

```bash
docker compose up --build
```

4. Open:

- `http://localhost:8000/docs`

The compose setup already handles the normal review flow. After the services are
up, use `http://localhost:8000/docs`.

### Local run

This is useful if you want to debug the API and worker manually without Docker.

#### Prerequisites

- Python `3.13`
- `uv`
- A reachable PostgreSQL instance

Install dependencies with:

```bash
uv sync
```

#### Steps

1. Copy the env file:

```bash
cp .env.example .env
```

2. Set local Postgres in `.env`:

```env
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/pelgo
```

3. Run migrations:

```bash
uv run alembic upgrade head
```

4. Optionally seed sample data:

```bash
uv run python scripts/seed.py
```

5. Start API:

```bash
uv run uvicorn pelgo.api.main:app --reload
```

6. Start worker in another shell:

```bash
uv run python -m pelgo.worker_main
```

## Optional Configuration

The current implementation keeps the configuration surface intentionally small,
but a few useful runtime knobs are already exposed through environment
variables.

| Setting                        | What it controls                            | Why it is useful                                                   |
| ------------------------------ | ------------------------------------------- | ------------------------------------------------------------------ |
| `LLM_PROVIDER`                 | Which LLM backend is used                   | Keeps the model layer configurable without rewriting orchestration |
| `LLM_MODEL`                    | Which model is used for prompts/tools       | Useful for balancing cost, speed, and quality                      |
| `TOP_GAP_LIMIT`                | How many skill gaps may be researched       | Lets you tune depth vs latency                                     |
| `RESEARCH_TIME_CAP_SECONDS`    | Hard cap for the research stage             | Keeps research bounded under slow external calls                   |
| `MIT_COURSE_LIMIT`             | How many MIT results to keep when available | Lets you tune the learning-resource output size                    |
| `WORKER_POLL_INTERVAL_SECONDS` | Worker polling frequency                    | Useful when balancing responsiveness vs DB polling noise           |
| `CANDIDATE_PDF_MAX_BYTES`      | Max accepted PDF size                       | Gives a simple safety limit for file uploads                       |

These knobs are intentionally limited. The goal was to keep the system easy to
reason about while still making the main latency, cost, and output-shape
trade-offs configurable.

## Worker Scaling

To verify concurrent workers locally:

```bash
docker compose up --build --scale worker=2
```

Worker logs include startup, idle state, job claims, completions, and failures,
plus worker host and PID for easier inspection.

## Tests

Focused verification suite:

```bash
uv run pytest \
  tests/test_api_schema_validation.py \
  tests/test_candidate_profile_extraction.py \
  tests/test_langgraph_routing.py \
  tests/test_match_status_response.py \
  tests/test_pii_redaction.py \
  tests/test_resource_selection.py \
  tests/test_worker_failure.py \
  tests/test_jd_url_tool.py
```

Integration test:

```bash
uv run pytest tests/test_integration_flow.py -m integration
```

The integration test is environment-gated and expects a working DB and LLM
configuration.

## AI-assisted development note

I used AI agents as a pair-programming and review partner during development.
They helped speed up implementation, surface alternatives, assist with
debugging, and challenge code quality. I also used them to pressure-test my own
solution ideas and trade-offs as the design evolved. I still reviewed the
outputs, set the quality bar, and made the final architectural, trade-off, and
integration decisions.

## What I would improve next

If I spent more time on this project, I would split the next work into two
buckets: short-term quality improvements and longer-term scaling paths.

### Short-term quality improvements

1. **Tighten the fallback candidate parser**

- `years_experience` is now more conservative on the LLM path, but the heuristic
  fallback is still simpler than I would want long-term.
- The next step would be to make the fallback parser narrower and less willing
  to over-infer experience totals.

2. **Improve JD extraction for difficult sites**

- Some JD URLs fail because they are blocked, JS-heavy, or anti-bot protected.
- The next step would be a better extraction layer for difficult pages, while
  keeping the current explicit-failure behavior for unsupported sites.

3. **Improve resource quality for practical skills**

- Resource selection is acceptable now, but still heuristic for some
  applied/tooling skills.
- The next step would be stronger reranking, better source quality control, and
  clearer provider preferences.

4. **Tighten fallback-resource behavior**

- Fallback resources keep the output structurally complete, which is useful.
- The next step would be making those fallbacks more intentional and less
  generic.

### Longer-term scaling paths

1. **Introduce a clearer failed-job / DLQ model**

- Today, terminal failures remain in the main jobs table with error detail and
  partial trace.
- A dedicated DLQ table would make operations cleaner once failed-job volume
  grows.

2. **Move beyond Postgres polling when scale justifies it**

- The current Postgres queue is the right complexity level for this assignment.
- If throughput, event fan-out, or worker coordination became more demanding, I
  would consider:
  - `NATS JetStream` for low-latency event delivery
  - `RabbitMQ` for durable work-queue semantics
  - `Kafka` for high-throughput streaming and retention-heavy event pipelines

3. **Add stronger crawling / extraction infrastructure**

- Today I intentionally avoided building a crawler-heavy stack.
- If business needs shifted toward broader JD coverage or stronger
  learning-resource discovery, I would add a more dedicated extraction layer for
  blocked or inconsistent sites.

4. **Lock preferred learning-content providers more aggressively**

- Right now the system prefers more targeted sources where possible and falls
  back to broader search when needed.
- If consistency became more important than broad discovery, I would move
  further toward curated providers such as MIT OCW, Coursera, or other
  controlled sources before allowing general search fallback.

5. **Consider a bounded ADK integration as a stretch path**

- I would not replace the whole orchestrator casually.
- But one bounded tool implemented with Google ADK could still be a useful
  future experiment if session/event semantics became valuable enough to justify
  the added integration surface.
