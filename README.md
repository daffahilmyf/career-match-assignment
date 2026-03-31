# Pelgo AI Lead Assignment

## Quickstart

1. Set environment variables (or copy `.env.example` to `.env`).
2. Run migrations:

```bash
uv run alembic upgrade head
```

3. Start API and worker:

```bash
uv run uvicorn pelgo.api.main:app --reload
uv run python -m pelgo.worker_main
```

4. Seed sample data:

```bash
uv run python scripts/seed.py
```

## API

- `POST /api/v1/candidate` - ingest resume text or base64 PDF
- `POST /api/v1/matches` - submit up to 10 JDs per candidate
- `GET /api/v1/matches/{job_id}` - status + result
- `GET /api/v1/matches?limit=20&offset=0&status=pending`
- `POST /api/v1/matches/{job_id}/requeue` - admin requeue

## System Prompt

JD extraction prompt:

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

Reasoning prompt (summary output):

```text
Write a 2-3 sentence reasoning summary for the match score. Use the candidate profile and the job description as context. Mention matched skills and key gaps in plain English. Keep it concise and avoid bullet points.
```

Planner prompt (tool sequence):

```text
You are orchestrating tools for a job match pipeline. Pick the single best next step based on the current state. Use assemble_result only when enough evidence has been gathered; if confidence is low, do not stop until gaps are prioritised and targeted research has been attempted.
```

## Framework Choice (1 sentence)

LangGraph provides a typed state machine with iterative planner decisions, explicit state transitions, and trace capture that fit the required agent_trace contract.

## Confidence Heuristic

Confidence is derived from measurable signals:
- JD completeness (required skills + responsibilities + seniority + domain)
- Skill coverage (matched required / total required)
- Seniority alignment (exact match vs unspecified vs mismatch)
- Domain overlap (candidate vs JD domain keywords)

Weighted confidence score: `0.2 * completeness + 0.35 * coverage + 0.25 * experience + 0.1 * seniority + 0.1 * domain`. Thresholds: high ≥ 0.75, medium ≥ 0.5, low < 0.5.

## Failure Modes (A4)

- Tool timeout: research tool has a timeout; on timeout the agent retries once and logs the failure with error_type=timeout.
- Invalid tool output: tool outputs are schema-validated before storage; failures cause a retry and log error_type=schema.
- Low confidence: low confidence triggers research tiering and does not silently return without enrichment.

## Caching

- JD URL caching uses `jd_cache` with a 7-day TTL and SHA-256 content hashing to avoid repeated extraction.

## Trade-offs

- Resume parsing uses heuristic extraction (name/email/skills/experience/education) to keep scope tight; production would use a dedicated parser or LLM extraction tool.
- Learning-resource discovery prefers direct MIT OpenCourseWare links first, then falls back to broader web results if MIT does not return usable matches.
- Structured logging is basic JSON to stdout, not a full log pipeline.

## Cuts (Documented)

- No ADK tool implementation.
- Minimal HTML frontend only; no full UI.

## Running with Docker

```bash
docker compose up --build
```

## Tests

```bash
DATABASE_URL=... LLM_PROVIDER=langchain_openai LLM_API_KEY=... uv run pytest -m integration
```
