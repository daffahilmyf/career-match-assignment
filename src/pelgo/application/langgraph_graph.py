from __future__ import annotations

import time
from typing import Iterable, Type, TypeVar, TYPE_CHECKING, cast

from langgraph.graph import END, StateGraph
from langgraph.types import Send

from pydantic import BaseModel

from pelgo.application.state import AgentState
from pelgo.domain.model.agent_evaluation_schema import ToolCallTrace
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsOutput,
    ResearchSkillResourcesOutput,
    ScoreCandidateOutput,
)
from pelgo.ports.tooling import ToolRegistry, validate_tool_registry

TOP_GAP_LIMIT = 3

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
    entry = ToolCallTrace(tool=tool_name, status=status, latency_ms=latency_ms)
    trace = list(state.get("trace_tool_calls", [])) + [entry]
    state["trace_tool_calls"] = trace
    if error_type or message:
        state["trace_last_error"] = {
            "tool": tool_name,
            "error_type": error_type,
            "message": message,
        }


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
        ranked = _require(state, "prioritized_gaps").ranked_skills
        if not ranked:
            yield Send("collect_resources", {})
            return
        for gap in ranked[:TOP_GAP_LIMIT]:
            yield Send("research_resource", {"gap_skill": gap.skill})

    def research_resource(state: AgentState) -> AgentState:
        tool = tools["research_skill_resources"]
        payload = tool.input_model(
            skill_name=_require(state, "gap_skill"),
            seniority_context=None,
        )
        output = _call_tool(
            state, "research_skill_resources", payload, tools, tool.output_model
        )
        state["resources"] = [cast(ResearchSkillResourcesOutput, output)]
        return state

    def collect_resources(state: AgentState) -> AgentState:
        return state

    graph.add_node("extract_requirements", extract_requirements)
    graph.add_node("score_candidate", score_candidate)
    graph.add_node("prioritise_gaps", prioritise_gaps)
    graph.add_node("research_resource", research_resource)
    graph.add_node("collect_resources", collect_resources)

    graph.set_entry_point("extract_requirements")
    graph.add_edge("extract_requirements", "score_candidate")
    graph.add_edge("score_candidate", "prioritise_gaps")
    graph.add_conditional_edges("prioritise_gaps", fanout_gaps)
    graph.add_edge("research_resource", "collect_resources")
    graph.add_edge("collect_resources", END)

    return graph.compile()
