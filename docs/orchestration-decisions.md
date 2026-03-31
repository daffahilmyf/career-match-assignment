# Research Decision Policies (Latency vs Quality)

This note captures candidate policies for deciding when the agent should
continue researching vs stop after core steps (extract -> score -> prioritize).
It is intended as a quick reference for review.

## Summary Recommendation

Preferred policy for latency + quality: **Tiered by Confidence**, optionally
with a **hard time cap** for the research stage.

## Decision Policies

### 1) Conditional (Confidence / Gap Gain)
- Rule: Research only if `confidence != high` or top gap gain >= X%.
- Pros: Cost-aware, flexible, defensible.
- Cons: Can stop early if confidence is noisy.
- Best when: You want strict cost control with explainability.

### 2) Fixed Budget
- Rule: Always research top N gaps (e.g., 1-2).
- Pros: Simple, predictable.
- Cons: Wastes calls on easy cases.
- Best when: You want deterministic outputs with minimal logic.

### 3) Tiered by Confidence (Recommended)
- Rule:
  - High confidence -> 0 research
  - Medium confidence -> research top 1
  - Low confidence -> research top 2-3
- Pros: Balances latency and quality; predictable and testable.
- Cons: Depends on confidence calibration.
- Best when: You need strong latency control without sacrificing quality.

### 4) Time-Budgeted
- Rule: Research until time cap reached (e.g., 20-30s).
- Pros: Strict latency bound.
- Cons: Non-deterministic outputs.
- Best when: You have strict response-time SLAs.

### 5) JD-Quality-Triggered
- Rule: Research only if JD quality is low (short/ambiguous).
- Pros: Avoids wasted calls on rich JDs.
- Cons: Requires reliable JD quality signal.
- Best when: JD inputs are noisy or inconsistent.

## Comparison Table

| Policy | Decision Rule | Pros | Cons | Best When |
|---|---|---|---|---|
| Conditional (Confidence/Gain) | Research if `confidence != high` or top gap gain >= X | Cost-aware, flexible, defensible | Can stop early if confidence is noisy | Strong cost control with explainability |
| Fixed Budget | Always research top N gaps | Simple, predictable | Wastes calls on easy cases | Deterministic outputs with minimal logic |
| Tiered by Confidence | High: 0, Medium: 1, Low: 2-3 research calls | Balances latency and quality; predictable | Depends on confidence calibration | Latency control without sacrificing quality |
| Time-Budgeted | Research until time cap | Strict latency bound | Non-deterministic outputs | Strict response-time SLAs |
| JD-Quality-Triggered | Research only if JD is short/ambiguous | Avoids wasted calls on rich JDs | Needs reliable JD quality signal | Noisy or inconsistent JD inputs |

## Recommended Default Policy (Latency + Quality)

- Use **Tiered by Confidence** with a **hard time cap** for the research stage.
- Suggested thresholds (tunable):
  - High -> 0 research
  - Medium -> top 1 gap
  - Low -> top 2-3 gaps
  - Hard time cap: 20-30s

## Confidence Heuristic Decision

We will use a **measurable, explainable heuristic** (no model self-reports or
benchmark-driven calibration for now) because the project timeline does not
allow reliable benchmarking.

### Chosen Strategy

- Use a weighted composite of observable signals:
  - JD completeness
  - Skill coverage (matched_required / required_total)
  - Seniority alignment
  - Domain overlap
- Produce `low | medium | high` based on simple thresholds.
- Rationale: defensible, auditable, and easy to tune later.

### Proposed Weights and Thresholds (Initial)

- Weights:
  - JD completeness: 0.2
  - Skill coverage: 0.4
  - Seniority alignment: 0.2
  - Domain overlap: 0.2
- Thresholds:
  - High: >= 0.75
  - Medium: 0.50 - 0.74
  - Low: < 0.50

### Deferred Alternatives

- Calibration via labeled validation set.
- Variance-based confidence (multi-run stability).
- Dual-signal consensus (heuristic + model self-confidence).

## Orchestration Provider Discussion (LangChain vs ADK)

This section captures the prior discussion about orchestration providers and
why LangGraph/LangChain vs Google ADK is a defensible choice for this project.

### Summary Recommendation

- If you want **strong orchestration and explicit state**: prefer LangGraph or ADK.
- If you want **fast iteration with familiar tooling**: LangChain is acceptable,
  but add explicit state machine, retries, and trace enforcement.

### LangChain (Pros/Cons)

- Pros:
  - Familiar ecosystem and patterns, easy to integrate with existing code.
  - Good tooling abstractions and prompt/tool wiring.
  - Lower ramp-up cost for this project.
- Cons:
  - Orchestration reliability depends on custom state handling.
  - Requires extra work for retries, idempotency, and traceability.

### Google ADK (Pros/Cons)

- Pros:
  - Strong orchestration primitives with stateful workflows.
  - Built-in patterns for traceability and agent lifecycle control.
  - Good fit when explicit orchestration is a top requirement.
- Cons:
  - Higher integration overhead if you are not already using ADK.
  - Adds vendor/tooling dependency; may be heavier than needed for the assignment.

### Trade-off Summary

- LangChain is the **fastest path** if you already use it, but you must
  implement state + retries + trace yourself.
- ADK is more **opinionated and orchestration-focused**, but adds
  integration cost and potential lock-in.

### Provider Comparison Table

| Criteria | LangChain | Google ADK |
|---|---|---|
| Orchestration Control | Medium (custom state needed) | High (built-in workflows) |
| State Machine Support | Low-Medium (manual) | High |
| Tooling Contracts | Medium (custom enforcement) | High |
| Traceability / Audit | Medium (manual trace) | High |
| Async/Queue Fit | Medium | High |
| Safety / Guardrails | Medium (custom) | High |
| Learning Curve | Low (familiar) | Medium |
| Interview Defensibility | Medium-High (if state added) | High |
| Vendor Lock-in Risk | Medium | High |
| Ecosystem Maturity | High | Medium |

## Orchestration Decision (Current)

- We will proceed with **LangGraph** for orchestration due to strong state
  semantics and parallel fan-out support.
- LangChain remains in the stack as the LLM client layer for provider-agnosticism.

## LLM Client Layer Decision

We will use **LangChain as the LLM client layer** to keep the system
provider-agnostic and flexible if we support multiple providers later. The
trade-off is small additional latency due to wrapper overhead, which is
acceptable for this assignment given the benefits in portability and future
extensibility.

### Considered Alternatives

- Direct provider SDK (lower latency, higher lock-in).
- LiteLLM (provider-agnostic but recent security concerns; deferred).
- Thin internal adapter (more control, more engineering work).
