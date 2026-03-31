# Orchestration Decisions

This document records the main orchestration decisions behind the current
implementation. It is written as a decision log: for each topic, I started from
my own constraints and preferred direction, used AI agents to pressure-test the
trade-offs, and then chose the final implementation path.

The goal here is not to list every possible design. It is to show the reasoning
behind the choices that shaped the system that was actually built.

---

## 1. Main Orchestrator

### Context

The system needs a runtime that can:
- carry typed state across steps
- choose the next tool at runtime
- handle tool failures without crashing the run
- produce a trustworthy execution trace

### Criteria

| Criteria | Why it mattered |
|---|---|
| State clarity | Typed state is both an assignment requirement and a practical debugging tool |
| Failure control | Tool failures should stay contained inside the run |
| Trace ownership | `agent_trace` must reflect runtime behavior, not model narration |
| Implementation speed | The solution had to be strong without becoming overbuilt |
| Dependency and security surface | I wanted to avoid extra integration layers unless they clearly improved the shipped system |
| Extensibility | The design should still leave room for future changes |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| LangGraph | Strong | Strong | Medium | Medium | Chosen |
| Google ADK | Strong | Strong | Medium | High | Strong option, but not the safest fit for this codebase now |
| LangChain-only orchestration | Medium | Medium | Medium | Low | Too weak for orchestration-heavy requirements |
| Custom loop | Strong | Strong | Medium | High | More engineering than this timebox justified |

### Decision

I chose **LangGraph** as the primary orchestrator.

It offered the cleanest balance between control and delivery speed. The project
needed explicit state, bounded routing, and runtime-owned trace data more than
it needed a highly open-ended agent loop.

Google ADK was the main alternative I took seriously. I did not reject it
because it was weak; in several areas it is actually strong. I rejected it
because, for this project, I wanted the smaller and more predictable dependency
surface. ADK can run directly on Google model backends, but for broader model
integration it also exposes wrappers such as `LiteLlm`, and LiteLLM has had
recent security concerns and compatibility issues around structured output in
real-world use. Even with patched versions available, I preferred to stay on a
simpler path unless ADK gave a clear advantage that the shipped system actually
needed.

### Implication

The system is intentionally structured. That gives up some flexibility, but it
makes the run easier to reason about, test, and review.

---

## 2. Planning Policy

### Context

The agent can either plan every step with the model, rely entirely on rules, or
combine both. I did not want to pay planning cost when the next step was
already obvious.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Predictability | Straightforward runs should behave consistently |
| Adaptability | Ambiguous runs should still get extra reasoning |
| Cost control | Planner calls add latency and model usage |
| Explainability | The routing policy should be easy to justify |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| LLM planner for every step | Medium | Medium | High | Medium | Too expensive for routine cases |
| Heuristics only | Strong | Strong | Low | Low | Predictable, but less adaptive |
| Heuristic-first, planner only on low confidence | Strong | Strong | Medium | Medium | Chosen |

### Decision

I chose **heuristic-first routing with planner escalation only for low-confidence runs**.

Most runs follow deterministic routing. When confidence is already low, the
planner is allowed to influence the next step.

### Implication

This keeps easy runs cheap and stable while still giving weak cases a more
deliberate path.

---

## 3. Skill Research Policy

### Context

Once the system identifies skill gaps, it needs to decide how much research to
do before assembling the final learning plan.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Learning-plan quality | The output should include useful next steps, not just a score |
| Latency control | Research must stay bounded |
| Cost control | External calls and extra LLM work should not expand freely |
| Stability | The behavior should remain testable and reviewable |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| Fixed research budget for every run | Strong | Strong | Medium | Low | Predictable, but inefficient |
| Strict tiering with `high -> 0` | Strong | Strong | Low | Low | Efficient, but can make plans thin |
| Tiered research with a hard time cap | Strong | Strong | Medium | Medium | Chosen |

### Decision

I chose **tiered research with a hard time cap**.

Current behavior:
- high confidence -> research up to 1 gap
- medium confidence -> research up to 1 gap
- low confidence -> research more aggressively, within a bounded limit
- research also stops when the time cap is reached

I kept **high confidence -> 1** instead of **0** because a concise, targeted
learning suggestion is usually more useful than no learning suggestion at all.

### Implication

This costs slightly more than a stricter policy, but it produces more complete
learning plans.

---

## 4. Confidence Heuristic

### Context

The system needs a confidence label for the score, but I did not want that label
to be based on the model simply asserting confidence.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Evidence-based reasoning | Confidence should come from measurable signals |
| Explainability | The heuristic should be easy to describe and review |
| Consistency | The same inputs should yield the same confidence |
| Implementation scope | The method had to fit the assignment timeline |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| Model self-reported confidence | Weak | Weak | Low | Low | Too subjective |
| Benchmark-calibrated confidence | Strong | Strong | Medium | High | Stronger in theory, too heavy here |
| Weighted heuristic from observable signals | Strong | Strong | Low | Medium | Chosen |

### Decision

I chose **a weighted heuristic** based on:
- JD completeness
- required skill coverage
- experience alignment
- seniority alignment
- domain overlap

### Implication

The result is practical rather than statistically calibrated, but it is easy to
inspect and does not rely on vague model self-assessment.

---

## 5. JD Extraction Failure Policy

### Context

JD extraction can fail for several reasons: malformed output, timeout, blocked
URL, or missing page. Earlier versions of the system could still return a
completed result after a failed URL extraction, which was misleading.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Output honesty | A broken URL should not quietly become a fake successful run |
| Resilience | One bad JD should not crash the worker |
| Practicality | Raw text and URL input fail in meaningfully different ways |
| Debuggability | Failure reasons should be visible from logs and API output |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| Always continue with fallback requirements | Medium | Medium | Low | Low | Too misleading for URL failures |
| Always fail the run | Strong | Strong | Medium | Low | Honest, but unnecessarily harsh for all cases |
| Treat raw text and URL input differently | Strong | Strong | Medium | Medium | Chosen |

### Decision

I chose **different failure semantics for raw text and JD URLs**.

Current behavior:
- raw text extraction failure can fall back to default/empty requirements
- JD URL extraction failure raises a clear job error after retries

### Implication

This makes URL-based failures more visible, but it avoids low-quality
“completed” results that were never based on a reliable JD extraction.

### Scaling path

I intentionally did not invest in a full crawler stack for this assignment. The
current approach is enough for public, directly fetchable pages, and that kept
the implementation time focused on the agent itself.

If this area needs to grow, the next step would be a dedicated crawling and
extraction layer for:
- job description URLs
- learning-resource discovery

That would help with issues such as:
- bot checks
- anti-scraping protections
- inconsistent page layouts
- pages that require stealth or browser-based rendering

Even then, I would only add that complexity when the product actually needs it.
For now, the more honest limitation is that some specific sites cannot be
crawled reliably, and those cases should fail clearly rather than pretending the
system extracted the JD correctly.

---

## 6. Resource Failure Policy

### Context

Resource lookup is useful, but it is not reliable enough to justify failing the
entire run when one lookup breaks.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Output usefulness | The learning plan should still be usable |
| Robustness | A failed lookup should not kill the entire job |
| Completeness | Prioritized gaps should not end with empty resource lists |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| Fail the whole run | Strong | Weak | Medium | Low | Too brittle |
| Return empty resources | Medium | Strong | Low | Low | Structurally valid, but weak output |
| Use fallback resources | Strong | Strong | Low | Medium | Chosen |

### Decision

I chose **fallback resources for failed or missing research results**.

If a prioritized gap has no researched resources, the final result still gets a
fallback resource entry.

### Implication

The learning plan stays complete, even when resource lookup quality is imperfect.

### Scaling path

Resource discovery follows the same principle as JD extraction: I kept it light
for this assignment instead of building a crawler-heavy retrieval layer.

If this area needed to scale in quality and coverage, I would consider:
- a dedicated crawler/extractor pipeline
- better handling for bot checks and blocked sites
- stronger page rendering/extraction for difficult sources
- more robust crawling policies for specific domains

That would improve coverage, but it would also add a lot of operational weight.
For the current system, the simpler choice was to accept that some sites are not
reliably crawlable and keep the behavior explicit.

---

## 7. Candidate Profile Extraction Strategy

### Context

Candidate profiles need to be structured enough for scoring, but resumes vary
widely. A rigid parser alone is not strong enough, while an LLM-only path would
make ingestion too fragile.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Extraction quality | Bad profile extraction weakens the whole scoring path |
| Reliability | Candidate ingestion should still work if the LLM path fails |
| Structured storage | The assignment requires structured candidate data in Postgres |
| Maintenance cost | The approach should stay practical to maintain |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| Heuristic only | Strong | Strong | Low | Low | Too brittle |
| LLM only | Medium | Medium | Medium | Low | Better quality, weaker resilience |
| LLM-first with heuristic fallback | Strong | Strong | Medium | Medium | Chosen |

### Decision

I chose **LLM-first extraction with heuristic fallback**.

I also tightened the prompt so `years_experience` is more conservative and based
on explicit evidence rather than optimistic inference.

### Implication

This improves the common path without turning the LLM into a single point of
failure.

---

## 8. Candidate Privacy Boundary

### Context

Candidate profiles can contain direct personal information. I wanted to reduce
unnecessary exposure before sending candidate context into the agent, and also
reduce the chance that irrelevant personal details influence the model's
reasoning.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Privacy improvement | Avoid sending obvious personal data when it is not needed |
| Fairness | Reduce the chance that irrelevant personal attributes influence the reasoning |
| Match quality | Keep the job-relevant content intact |
| Simplicity | The solution needed to stay lightweight |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| Send raw profile | Strong | Strong | Low | Low | Too loose on privacy |
| Full de-identification system | Strong | Strong | High | High | Too heavy for this scope |
| Lightweight redaction before orchestration | Strong | Strong | Low | Medium | Chosen |

### Decision

I chose **lightweight PII redaction before candidate context enters the agent**.

This was not only a privacy decision. It was also a fairness decision. The more
I can keep the model focused on job-relevant skills, experience, and role fit,
the less likely it is to anchor on personal details that should not matter to
the match.

### Implication

The system gets a meaningful privacy improvement without adding a large
compliance-heavy subsystem, and it also creates a cleaner boundary around what
information is actually relevant to the matching task.

---

## 9. Queue and Worker Model

### Context

The assignment requires out-of-process workers, safe concurrent job claiming,
retries, and terminal failure handling.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Concurrency safety | Two workers should not process the same job twice |
| Simplicity | Local setup and review should stay straightforward |
| Durability | Job state should survive worker restarts |
| Defensibility | The design should be easy to explain and test |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| Postgres-backed queue | Strong | Strong | Medium | Low | Chosen |
| External broker from day one | Medium | Strong | Medium | High | Reasonable future path, not necessary now |
| In-process threads | Weak | Weak | Low | Low | Not suitable for the assignment |

### Decision

I chose **a Postgres-backed queue with out-of-process workers**.

Claiming uses `FOR UPDATE SKIP LOCKED`, and failed jobs retry with backoff
before moving to a terminal `failed` state.

### Implication

This is less sophisticated than a broker-based system, but it is simple,
durable, and appropriate for the assignment scope.

### Scaling path

If this needs to scale further, the next queue decision depends on what matters
most:
- if the priority is low-latency event delivery and lightweight operations, a
  broker like **NATS JetStream** becomes attractive
- if the priority is durable work queues with familiar worker patterns,
  **RabbitMQ** is a reasonable next step
- if the priority is very high-throughput streaming and event retention,
  **Kafka** is a better fit

I could have introduced one of these on day one, but it would have added
meaningful operational complexity without improving the assignment outcome much.
For the current scope, Postgres as the source of truth and queue is the simpler
and more practical choice.

---

## 10. Trace Ownership

### Context

The assignment requires `agent_trace`. To be useful, it needs to describe what
the runtime actually did, not what the model claims it did.

### Criteria

| Criteria | Why it mattered |
|---|---|
| Trustworthiness | Trace data should come from runtime facts |
| Auditability | The trace should help debug both success and failure |
| Clarity | The source of truth should be obvious |

### Options Compared

| Option | State clarity | Failure control | Cost/latency | Complexity | Final take |
|---|---|---|---|---|---|
| LLM-generated trace | Weak | Weak | Low | Low | Not trustworthy enough |
| Runtime-owned trace | Strong | Strong | Low | Medium | Chosen |
| Mixed ownership | Medium | Medium | Medium | High | Too ambiguous |

### Decision

I chose **runtime-owned trace only**.

That means:
- `tool_calls` come from orchestration
- `total_llm_calls` comes from runtime counting
- `fallbacks_triggered` comes from runtime fallback behavior

### Implication

The trace is more trustworthy, though it does require a brief explanation that
`tool_calls` and `total_llm_calls` are intentionally different metrics.

---

## Open Decisions

These are the few decisions I would still revisit if I had more time.

| Topic | Current choice | Why it is still open |
|---|---|---|
| High-confidence research | Research up to 1 gap | I could tighten this to 0 for lower cost |
| Fallback years parser | Keep simple heuristic fallback | The LLM path is better now, but fallback can still be improved |
| Failed-job storage model | Keep terminal failed jobs in Postgres | A dedicated DLQ table could make operations cleaner |
| Google ADK | Not used as primary orchestrator | Still a good stretch option for one bounded tool |

