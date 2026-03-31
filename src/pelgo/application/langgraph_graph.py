from __future__ import annotations

import time
from typing import Iterable, Type, TypeVar, cast
from uuid import UUID, uuid4

import requests
from langgraph.graph import END, StateGraph
from langgraph.types import Send

from pydantic import BaseModel, ValidationError

from pelgo.application.config import AppSettings
from pelgo.application.state import AgentState, ResearchResourceEntry
from pelgo.domain.model.agent_evaluation_schema import (
    AgentEvaluationResult,
    AgentExecutionTrace,
    DimensionMatchScores,
    LearningPlanItem,
    LearningResource,
    ToolCallTrace,
)
from pelgo.domain.model.shared_types import ConfidenceLevel
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsOutput,
    ResearchSkillResourcesOutput,
    ScoreCandidateOutput,
    SkillResource,
)
from pelgo.ports.llm import LLMClient
from pelgo.ports.tooling import ToolRegistry, validate_tool_registry

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


class ReasoningResponse(BaseModel):
    reasoning: str


def _require(state: AgentState, key: str):
    if key not in state:
        raise KeyError(f"Missing required state key: {key}")
    return state[key]


def _bump_fallbacks(state: AgentState) -> None:
    state["fallbacks_triggered"] = state.get("fallbacks_triggered", 0) + 1


def _record_trace(
    state: AgentState,
    tool_name: str,
    status: str,
    latency_ms: int,
    error_type: str | None = None,
    message: str | None = None,
) -> None:
    call_id = uuid4().hex
    entry = ToolCallTrace(
        tool=tool_name,
        status=status,
        latency_ms=latency_ms,
        call_id=call_id,
    )
    trace = list(state.get("trace_tool_calls", [])) + [entry]
    state["trace_tool_calls"] = trace
    if error_type or message:
        errors = list(state.get("trace_errors", [])) + [
            {
                "tool": tool_name,
                "error_type": error_type,
                "message": message,
                "call_id": call_id,
            }
        ]
        state["trace_errors"] = errors


def _call_tool(
    state: AgentState,
    tool_name: str,
    payload: BaseModel,
    tools: ToolRegistry,
    output_model: Type[BaseModelT],
    llm_call: bool = False,
    max_attempts: int = 1,
) -> BaseModelT:
    tool = tools[tool_name]
    attempt = 0
    while True:
        attempt += 1
        start = time.perf_counter()
        try:
            raw_output = tool(payload)
            output = output_model.model_validate(raw_output)
            latency_ms = int((time.perf_counter() - start) * 1000)
            _record_trace(state, tool_name, "success", latency_ms)
            if llm_call:
                state["total_llm_calls"] = state.get("total_llm_calls", 0) + 1
            return output
        except (ValidationError, requests.Timeout) as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            _record_trace(
                state,
                tool_name,
                "error",
                latency_ms,
                error_type=exc.__class__.__name__,
                message=str(exc),
            )
            if attempt < max_attempts:
                _bump_fallbacks(state)
                continue
            raise
        except Exception as exc:
            latency_ms = int((time.perf_counter() - start) * 1000)
            _record_trace(
                state,
                tool_name,
                "error",
                latency_ms,
                error_type=exc.__class__.__name__,
                message=str(exc),
            )
            raise


def _research_limit(state: AgentState, settings: AppSettings) -> int:
    score: ScoreCandidateOutput = _require(state, "score")
    if score.confidence == ConfidenceLevel.high:
        return 0
    if score.confidence == ConfidenceLevel.medium:
        return 1
    return settings.top_gap_limit


def _to_learning_resources(resources: list[SkillResource]) -> list[LearningResource]:
    return [LearningResource.model_validate(resource) for resource in resources]


def _build_learning_plan(state: AgentState, settings: AppSettings) -> list[LearningPlanItem]:
    prioritized: PrioritiseSkillGapsOutput = _require(state, "prioritized_gaps")
    resources = state.get("researched_resources", [])
    resources_by_skill = {entry["skill"]: entry["resources"] for entry in resources}

    gaps = prioritized.ranked_skills[: settings.top_gap_limit]
    plan: list[LearningPlanItem] = []
    for gap in gaps:
        skill_resources = resources_by_skill.get(gap.skill, [])
        plan.append(
            LearningPlanItem(
                skill=gap.skill,
                priority_rank=gap.priority_rank,
                estimated_match_gain_pct=gap.estimated_match_gain_pct,
                resources=_to_learning_resources(skill_resources),
                rationale=gap.rationale,
            )
        )
    return plan


def _build_reasoning(
    llm: LLMClient | None,
    score: ScoreCandidateOutput,
    requirements: ExtractJDRequirementsOutput,
    candidate_profile: str,
    job_input: str,
) -> tuple[str, bool]:
    if llm is None:
        return (
            "Match score and learning plan were generated from the job requirements, "
            "skill coverage, seniority alignment, and domain overlap signals. "
            "This summary explains the overall fit and highlights the highest-impact gaps.",
            False,
        )

    prompt = (
        "Write a 2-3 sentence reasoning summary for the match score. "
        "Use the candidate profile and the job description as context. "
        "Mention matched skills and key gaps in plain English. "
        "Keep it concise and avoid bullet points.\n\n"
        f"Candidate profile (summary): {candidate_profile}\n"
        f"Job description (summary): {job_input}\n"
        f"Matched skills: {', '.join(score.matched_skills)}\n"
        f"Gap skills: {', '.join(score.gap_skills)}\n"
        f"Seniority: {requirements.seniority_level}\n"
        f"Domain: {requirements.domain}\n"
    )
    response = llm.complete_json(prompt, ReasoningResponse)
    return response.reasoning, True


def _dedupe_trace(trace_calls: list[ToolCallTrace]) -> list[ToolCallTrace]:
    seen: set[str] = set()
    deduped: list[ToolCallTrace] = []
    for entry in trace_calls:
        if entry.call_id in seen:
            continue
        seen.add(entry.call_id)
        deduped.append(entry)
    return deduped


def _resolve_gap_skills(score: ScoreCandidateOutput, prioritized: PrioritiseSkillGapsOutput) -> list[str]:
    if score.gap_skills:
        return score.gap_skills
    if prioritized.ranked_skills:
        return [gap.skill for gap in prioritized.ranked_skills]
    return []


def build_graph(
    tools: ToolRegistry, settings: AppSettings | None = None, llm: LLMClient | None = None
):
    validate_tool_registry(tools)
    settings = settings or AppSettings()

    graph = StateGraph(AgentState)

    def extract_requirements(state: AgentState) -> AgentState:
        tool = tools["extract_jd_requirements"]
        payload = tool.input_model(job_url_or_text=_require(state, "job_input"))
        output = _call_tool(
            state,
            "extract_jd_requirements",
            payload,
            tools,
            tool.output_model,
            llm_call=True,
            max_attempts=2,
        )
        state["requirements"] = cast(ExtractJDRequirementsOutput, output)
        return state

    def score_candidate(state: AgentState) -> AgentState:
        tool = tools["score_candidate_against_requirements"]
        payload = tool.input_model(
            candidate_profile=_require(state, "candidate_profile"),
            requirements=_require(state, "requirements"),
        )
        output = _call_tool(
            state,
            "score_candidate_against_requirements",
            payload,
            tools,
            tool.output_model,
        )
        state["score"] = cast(ScoreCandidateOutput, output)
        return state

    def prioritise_gaps(state: AgentState) -> AgentState:
        tool = tools["prioritise_skill_gaps"]
        payload = tool.input_model(
            gap_skills=_require(state, "score").gap_skills,
            job_market_context=_require(state, "job_input"),
        )
        output = _call_tool(
            state, "prioritise_skill_gaps", payload, tools, tool.output_model
        )
        state["prioritized_gaps"] = cast(PrioritiseSkillGapsOutput, output)
        return state

    def fanout_gaps(state: AgentState) -> Iterable[Send]:
        limit = _research_limit(state, settings)
        if limit == 0:
            score: ScoreCandidateOutput = _require(state, "score")
            if score.confidence == ConfidenceLevel.low:
                _bump_fallbacks(state)
                limit = 1
            else:
                yield Send("collect_resources", {})
                return
        ranked = _require(state, "prioritized_gaps").ranked_skills
        if not ranked:
            yield Send("collect_resources", {})
            return
        if "research_started_at" not in state:
            state["research_started_at"] = time.perf_counter()
        ranked_sorted = sorted(ranked, key=lambda gap: gap.priority_rank)
        for gap in ranked_sorted[:limit]:
            yield Send("research_resource", {"gap_skill": gap.skill})

    def research_resource(state: AgentState) -> AgentState:
        started_at = state.get("research_started_at")
        if started_at is not None:
            if time.perf_counter() - started_at > settings.research_time_cap_seconds:
                return state
        tool = tools["research_skill_resources"]
        payload = tool.input_model(
            skill_name=_require(state, "gap_skill"),
            seniority_context=None,
        )
        output = _call_tool(
            state, "research_skill_resources", payload, tools, tool.output_model
        )
        resource_output = cast(ResearchSkillResourcesOutput, output)
        state["resources"] = [resource_output]
        entry: ResearchResourceEntry = {
            "skill": _require(state, "gap_skill"),
            "resources": resource_output.resources,
        }
        state["researched_resources"] = [entry]
        return state

    def collect_resources(state: AgentState) -> AgentState:
        resources = state.get("resources", [])
        state["resources"] = resources
        return state

    def assemble_result(state: AgentState) -> AgentState:
        score: ScoreCandidateOutput = _require(state, "score")
        requirements: ExtractJDRequirementsOutput = _require(state, "requirements")
        prioritized: PrioritiseSkillGapsOutput = _require(state, "prioritized_gaps")
        trace_calls = _dedupe_trace(state.get("trace_tool_calls", []))
        summary, used_llm = _build_reasoning(
            llm,
            score,
            requirements,
            _require(state, "candidate_profile"),
            _require(state, "job_input"),
        )
        if used_llm:
            state["total_llm_calls"] = state.get("total_llm_calls", 0) + 1
        execution_trace = AgentExecutionTrace(
            tool_calls=trace_calls,
            total_llm_calls=state.get("total_llm_calls", 0),
            fallbacks_triggered=state.get("fallbacks_triggered", 0),
        )
        plan = _build_learning_plan(state, settings)
        gap_skills = _resolve_gap_skills(score, prioritized)
        result = AgentEvaluationResult(
            job_id=UUID(_require(state, "job_id")),
            overall_match_score=score.overall_score,
            confidence_level=score.confidence,
            dimension_match_scores=DimensionMatchScores(
                skills=score.dimension_scores.skills,
                experience=score.dimension_scores.experience,
                seniority_fit=score.dimension_scores.seniority_fit,
            ),
            matched_skill_tags=score.matched_skills,
            missing_skill_tags=gap_skills,
            summary=summary,
            learning_plan=plan,
            execution_trace=execution_trace,
        )
        state["result"] = result
        return state

    graph.add_node("extract_requirements", extract_requirements)
    graph.add_node("score_candidate", score_candidate)
    graph.add_node("prioritise_gaps", prioritise_gaps)
    graph.add_node("research_resource", research_resource)
    graph.add_node("collect_resources", collect_resources)
    graph.add_node("assemble_result", assemble_result)

    graph.set_entry_point("extract_requirements")
    graph.add_edge("extract_requirements", "score_candidate")
    graph.add_edge("score_candidate", "prioritise_gaps")
    graph.add_conditional_edges("prioritise_gaps", fanout_gaps)
    graph.add_edge("research_resource", "collect_resources")
    graph.add_edge("collect_resources", "assemble_result")
    graph.add_edge("assemble_result", END)

    return graph.compile()
