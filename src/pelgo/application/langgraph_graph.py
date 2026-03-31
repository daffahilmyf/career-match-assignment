from __future__ import annotations

import time
from typing import Iterable, Type, TypeVar, cast
from uuid import UUID, uuid4

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from pydantic import BaseModel

from pelgo.application.state import AgentState, ResearchResourceEntry
from pelgo.domain.model.agent_evaluation_schema import (
    AgentEvaluationResult,
    AgentExecutionTrace,
    DimensionMatchScores,
    LearningPlanItem,
    ToolCallTrace,
)
from pelgo.domain.model.shared_types import ConfidenceLevel
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsOutput,
    ResearchSkillResourcesOutput,
    ScoreCandidateOutput,
)
from pelgo.ports.tooling import ToolRegistry, validate_tool_registry

TOP_GAP_LIMIT = 3
RESEARCH_TIME_CAP_SECONDS = 25

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


def _require(state: AgentState, key: str):
    if key not in state:
        raise KeyError(f"Missing required state key: {key}")
    return state[key]


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
) -> BaseModelT:
    tool = tools[tool_name]
    start = time.perf_counter()
    try:
        raw_output = tool(payload)
        output = output_model.model_validate(raw_output)
        latency_ms = int((time.perf_counter() - start) * 1000)
        _record_trace(state, tool_name, "success", latency_ms)
        return output
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


def _research_limit(state: AgentState) -> int:
    score: ScoreCandidateOutput = _require(state, "score")
    if score.confidence == ConfidenceLevel.high:
        return 0
    if score.confidence == ConfidenceLevel.medium:
        return 1
    return TOP_GAP_LIMIT


def _build_learning_plan(state: AgentState) -> list[LearningPlanItem]:
    prioritized: PrioritiseSkillGapsOutput = _require(state, "prioritized_gaps")
    resources = state.get("researched_resources", [])
    resources_by_skill = {entry["skill"]: entry["resources"] for entry in resources}

    plan: list[LearningPlanItem] = []
    for gap in prioritized.ranked_skills[:TOP_GAP_LIMIT]:
        plan.append(
            LearningPlanItem(
                skill=gap.skill,
                priority_rank=gap.priority_rank,
                estimated_match_gain_pct=gap.estimated_match_gain_pct,
                resources=resources_by_skill.get(gap.skill, []),
                rationale=gap.rationale,
            )
        )
    return plan


def build_graph(tools: ToolRegistry):
    validate_tool_registry(tools)

    graph = StateGraph(AgentState)

    def extract_requirements(state: AgentState) -> AgentState:
        tool = tools["extract_jd_requirements"]
        payload = tool.input_model(job_url_or_text=_require(state, "job_input"))
        output = _call_tool(
            state, "extract_jd_requirements", payload, tools, tool.output_model
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
        limit = _research_limit(state)
        if limit == 0:
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
            if time.perf_counter() - started_at > RESEARCH_TIME_CAP_SECONDS:
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
        trace_calls = state.get("trace_tool_calls", [])
        execution_trace = AgentExecutionTrace(
            tool_calls=trace_calls,
            total_llm_calls=0,
            fallbacks_triggered=0,
        )
        plan = _build_learning_plan(state)
        summary = "Match score and learning plan generated based on job requirements."
        result = AgentEvaluationResult(
            job_id=UUID(_require(state, "job_id")),
            overall_score=score.overall_score,
            confidence=score.confidence,
            dimension_scores=DimensionMatchScores(
                skills=score.dimension_scores.skills,
                experience=score.dimension_scores.experience,
                seniority_fit=score.dimension_scores.seniority_fit,
            ),
            matched_skills=score.matched_skills,
            gap_skills=score.gap_skills,
            reasoning=summary,
            learning_plan=plan,
            agent_trace=execution_trace,
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
