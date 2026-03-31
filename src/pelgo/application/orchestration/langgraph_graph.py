from __future__ import annotations

import time
from typing import Type, TypeVar, cast
from urllib.parse import quote_plus

import requests
from pydantic import BaseModel, ValidationError

from langgraph.graph import END, StateGraph

from pelgo.application.config import AppSettings
from pelgo.application.bootstrap.tools import ToolRegistry
from pelgo.application.orchestration.state import AgentState
from pelgo.domain.model.agent_evaluation_schema import (
    AgentEvaluationResult,
    AgentTrace,
    LearningResource,
    ToolCallTrace,
)
from pelgo.domain.model.shared_types import ConfidenceLevel
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsOutput,
    ResearchSkillResourcesOutput,
    ScoreCandidateOutput,
)
from pelgo.ports.llm import LLMClient
from pelgo.prompts.templates import PLANNER_PROMPT, REASONING_PROMPT

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


class ReasoningResponse(BaseModel):
    reasoning: str


class PlanResponse(BaseModel):
    next_step: str | None = None
    should_stop: bool = False


VALID_NEXT_STEPS = {
    "extract_jd_requirements",
    "score_candidate_against_requirements",
    "prioritise_skill_gaps",
    "research_skill_resources",
    "assemble_result",
}


def _require(state: AgentState, key: str):
    if key not in state:
        raise KeyError(f"Missing required state key: {key}")
    return state[key]


def _render_template(template: str, values: dict[str, str]) -> str:
    for key, value in values.items():
        template = template.replace(f"{{{{{key}}}}}", value)
    return template


def _record_trace(
    state: AgentState,
    tool: str,
    status: str,
    latency_ms: int,
) -> None:
    entry = ToolCallTrace(tool=tool, status=status, latency_ms=latency_ms)
    existing = state.get("trace_tool_calls", [])
    state["trace_tool_calls"] = [*existing, entry]


def _bump_fallbacks(state: AgentState) -> None:
    state["fallbacks_triggered"] = state.get("fallbacks_triggered", 0) + 1


def _current_llm_calls(state: AgentState, llm: LLMClient | None) -> int:
    if llm is not None:
        try:
            return llm.call_count()
        except Exception:
            pass
    return state.get("total_llm_calls", 0)


def _call_tool(
    state: AgentState,
    tool_name: str,
    payload: BaseModel,
    tools: ToolRegistry,
    output_model: Type[BaseModelT],
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
            return output
        except ValidationError:
            latency_ms = int((time.perf_counter() - start) * 1000)
            _record_trace(state, tool_name, "failed", latency_ms)
            if attempt >= max_attempts:
                raise
            _bump_fallbacks(state)
            time.sleep(0.2 * attempt)
        except requests.Timeout:
            latency_ms = int((time.perf_counter() - start) * 1000)
            _record_trace(state, tool_name, "failed", latency_ms)
            if attempt >= max_attempts:
                raise
            _bump_fallbacks(state)
            time.sleep(0.2 * attempt)
        except requests.RequestException:
            latency_ms = int((time.perf_counter() - start) * 1000)
            _record_trace(state, tool_name, "failed", latency_ms)
            if attempt >= max_attempts:
                raise
            _bump_fallbacks(state)
            time.sleep(0.2 * attempt)


def _build_reasoning(
    llm: LLMClient | None,
    score: ScoreCandidateOutput,
    requirements: ExtractJDRequirementsOutput,
    candidate_profile: str,
    job_input: str,
) -> str:
    if llm is None:
        return (
            "Match score and learning plan were generated from the job requirements, "
            "skill coverage, experience fit, seniority alignment, and domain overlap signals. "
            "This summary explains the overall fit and highlights the highest-impact gaps."
        )
    prompt = _render_template(
        REASONING_PROMPT,
        {
            "candidate_profile": candidate_profile,
            "job_input": job_input,
            "matched_skills": ", ".join(score.matched_skills),
            "gap_skills": ", ".join(score.gap_skills),
            "domain": requirements.domain,
        },
    )
    response = llm.complete_json(prompt, ReasoningResponse)
    return response.reasoning


def _research_limit(state: AgentState, settings: AppSettings) -> int:
    score: ScoreCandidateOutput = _require(state, "score")
    if score.confidence == ConfidenceLevel.high:
        return 1
    if score.confidence == ConfidenceLevel.medium:
        return 1
    return max(2, settings.top_gap_limit)



def _fallback_resource_output(skill_name: str) -> ResearchSkillResourcesOutput:
    query = quote_plus(skill_name)
    return ResearchSkillResourcesOutput(
        resources=[
            {
                "title": f"MIT OCW Search: {skill_name}",
                "url": f"https://ocw.mit.edu/search/?q={query}",
                "estimated_hours": 6,
                "type": "course",
            }
        ],
        relevance_score=40,
    )


def _remaining_researchable_gaps(state: AgentState) -> list[str]:
    prioritized = state.get("prioritized_gaps")
    if prioritized is None:
        return []
    ranked_skills = [gap.skill for gap in prioritized.ranked_skills]
    researched = {entry["skill"] for entry in state.get("researched_resources", [])}
    attempted = set(state.get("attempted_research_skills", []))
    return [skill for skill in ranked_skills if skill not in researched and skill not in attempted]


def _heuristic_next_step(state: AgentState, settings: AppSettings) -> str:
    if "requirements" not in state:
        return "extract_jd_requirements"
    if "score" not in state:
        return "score_candidate_against_requirements"

    score: ScoreCandidateOutput = state["score"]
    has_gaps = bool(score.gap_skills)
    if not has_gaps:
        return "assemble_result"

    if "prioritized_gaps" not in state:
        return "prioritise_skill_gaps"
    if state.get("research_exhausted"):
        return "assemble_result"

    remaining_gaps = _remaining_researchable_gaps(state)
    if not remaining_gaps:
        return "assemble_result"

    limit = _research_limit(state, settings)
    researched_count = len(state.get("researched_resources", []))
    if researched_count < limit:
        return "research_skill_resources"

    return "assemble_result"


def _plan_next_step(llm: LLMClient | None, state: AgentState, settings: AppSettings) -> str:
    heuristic = _heuristic_next_step(state, settings)
    if llm is None:
        return heuristic

    score = state.get("score")
    if score is None:
        return heuristic

    if score.confidence != ConfidenceLevel.low:
        return heuristic

    prompt = _render_template(
        PLANNER_PROMPT,
        {
            "has_requirements": str("requirements" in state),
            "has_score": str("score" in state),
            "has_prioritized_gaps": str("prioritized_gaps" in state),
            "researched_resource_count": str(len(state.get("researched_resources", []))),
            "score_confidence": getattr(score, "confidence", "unknown"),
            "gap_count": str(len(score.gap_skills) if score else 0),
        },
    )
    response = llm.complete_json(prompt, PlanResponse)
    if response.should_stop:
        return "assemble_result"
    next_step = response.next_step or heuristic
    if next_step not in VALID_NEXT_STEPS:
        return heuristic
    return next_step


def build_graph(tools: ToolRegistry, settings: AppSettings, llm: LLMClient | None) -> StateGraph:
    graph = StateGraph(AgentState)

    def plan(state: AgentState) -> AgentState:
        state["total_llm_calls"] = _current_llm_calls(state, llm)
        return state

    def extract_requirements(state: AgentState) -> AgentState:
        tool = tools["extract_jd_requirements"]
        payload = tool.input_model(job_url_or_text=_require(state, "job_input"))
        try:
            output = _call_tool(
                state,
                "extract_jd_requirements",
                payload,
                tools,
                tool.output_model,
                max_attempts=2,
            )
            state["requirements"] = cast(ExtractJDRequirementsOutput, output)
        except Exception:
            _bump_fallbacks(state)
            state["requirements"] = ExtractJDRequirementsOutput(
                required_skills=[],
                nice_to_have_skills=[],
                seniority_level="unspecified",
                domain="",
                responsibilities=[],
            )
        state["total_llm_calls"] = _current_llm_calls(state, llm)
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
        state["total_llm_calls"] = _current_llm_calls(state, llm)
        return state

    def prioritise_gaps(state: AgentState) -> AgentState:
        tool = tools["prioritise_skill_gaps"]
        payload = tool.input_model(
            gap_skills=_require(state, "score").gap_skills,
            job_market_context=_require(state, "job_input"),
        )
        output = _call_tool(state, "prioritise_skill_gaps", payload, tools, tool.output_model)
        state["prioritized_gaps"] = cast(PrioritiseSkillGapsOutput, output)
        state["total_llm_calls"] = _current_llm_calls(state, llm)
        return state

    def research_resource(state: AgentState) -> AgentState:
        limit = _research_limit(state, settings)
        if limit <= 0:
            return state
        ranked = _require(state, "prioritized_gaps").ranked_skills
        if not ranked:
            return state
        if "research_started_at" not in state:
            state["research_started_at"] = time.perf_counter()

        tool = tools["research_skill_resources"]
        limit_seconds = settings.research_time_cap_seconds
        resources_outputs = list(state.get("resources", []))
        researched_entries = list(state.get("researched_resources", []))
        attempted_skills = list(state.get("attempted_research_skills", []))
        already_researched = {entry["skill"] for entry in researched_entries}
        attempted_set = set(attempted_skills)

        for gap in ranked:
            if gap.skill in already_researched or gap.skill in attempted_set:
                continue
            elapsed = time.perf_counter() - state["research_started_at"]
            if elapsed >= limit_seconds or len(researched_entries) >= limit:
                state["research_exhausted"] = True
                if elapsed >= limit_seconds:
                    _bump_fallbacks(state)
                break
            payload = tool.input_model(
                skill_name=gap.skill,
                seniority_context=_require(state, "requirements").seniority_level,
            )
            attempted_skills.append(gap.skill)
            attempted_set.add(gap.skill)
            try:
                output = _call_tool(state, "research_skill_resources", payload, tools, tool.output_model)
            except Exception:
                _bump_fallbacks(state)
                resource_output = _fallback_resource_output(gap.skill)
            else:
                resource_output = cast(ResearchSkillResourcesOutput, output)
                if not resource_output.resources:
                    resource_output = _fallback_resource_output(gap.skill)
            resources_outputs.append(resource_output)
            researched_entries.append({"skill": gap.skill, "resources": resource_output.resources})

        if not _remaining_researchable_gaps({**state, "researched_resources": researched_entries, "attempted_research_skills": attempted_skills}):
            state["research_exhausted"] = True
        state["resources"] = resources_outputs
        state["researched_resources"] = researched_entries
        state["attempted_research_skills"] = attempted_skills
        state["total_llm_calls"] = _current_llm_calls(state, llm)
        return state

    def assemble_result(state: AgentState) -> AgentState:
        score: ScoreCandidateOutput = _require(state, "score")
        requirements: ExtractJDRequirementsOutput = _require(state, "requirements")
        prioritized: PrioritiseSkillGapsOutput
        if "prioritized_gaps" in state:
            prioritized = state["prioritized_gaps"]
        else:
            prioritized = PrioritiseSkillGapsOutput(ranked_skills=[])
        trace_calls = state.get("trace_tool_calls", [])
        reasoning = _build_reasoning(
            llm,
            score,
            requirements,
            _require(state, "candidate_profile"),
            _require(state, "job_input"),
        )
        state["total_llm_calls"] = _current_llm_calls(state, llm)
        plan_resources = state.get("researched_resources", [])
        resources_by_skill: dict[str, list[LearningResource]] = {}
        for entry in plan_resources:
            resources_by_skill[entry["skill"]] = [
                LearningResource.model_validate(
                    resource.model_dump() if hasattr(resource, "model_dump") else resource
                )
                for resource in entry["resources"]
            ]
        learning_plan = []
        for ranked in prioritized.ranked_skills:
            learning_plan.append(
                {
                    "skill": ranked.skill,
                    "priority_rank": ranked.priority_rank,
                    "estimated_match_gain_pct": ranked.estimated_match_gain_pct,
                    "resources": resources_by_skill.get(ranked.skill, []),
                    "rationale": ranked.rationale,
                }
            )

        agent_trace = AgentTrace(
            tool_calls=trace_calls,
            total_llm_calls=state.get("total_llm_calls", 0),
            fallbacks_triggered=state.get("fallbacks_triggered", 0),
        )
        result = AgentEvaluationResult(
            job_id=str(_require(state, "job_id")),
            overall_score=score.overall_score,
            confidence=score.confidence,
            dimension_scores=score.dimension_scores,
            matched_skills=score.matched_skills,
            gap_skills=score.gap_skills,
            reasoning=reasoning,
            learning_plan=learning_plan,
            agent_trace=agent_trace,
        )
        state["result"] = result
        return state

    def route_by_plan(state: AgentState) -> str:
        requested = _plan_next_step(llm, state, settings)
        heuristic = _heuristic_next_step(state, settings)

        if requested == "extract_jd_requirements" and "requirements" in state:
            return heuristic
        if requested == "score_candidate_against_requirements" and "score" in state:
            return heuristic
        if requested == "prioritise_skill_gaps" and "prioritized_gaps" in state:
            return heuristic
        if requested == "research_skill_resources":
            if "prioritized_gaps" not in state:
                return "prioritise_skill_gaps"
            if state.get("research_exhausted"):
                return "assemble_result"
            if not _remaining_researchable_gaps(state):
                return "assemble_result"
            if len(state.get("researched_resources", [])) >= _research_limit(state, settings):
                return heuristic

        if requested == "assemble_result":
            score = state.get("score")
            if not score:
                return heuristic
            if score.confidence == ConfidenceLevel.low and score.gap_skills:
                if "prioritized_gaps" not in state:
                    return "prioritise_skill_gaps"
                if not state.get("research_exhausted") and _remaining_researchable_gaps(state) and len(state.get("researched_resources", [])) < _research_limit(state, settings):
                    return "research_skill_resources"

        if requested == "score_candidate_against_requirements" and "requirements" not in state:
            return "extract_jd_requirements"
        if requested in {"prioritise_skill_gaps", "research_skill_resources", "assemble_result"} and "score" not in state:
            if "requirements" not in state:
                return "extract_jd_requirements"
            return "score_candidate_against_requirements"

        return requested

    graph.add_node("plan", plan)
    graph.add_node("extract_requirements", extract_requirements)
    graph.add_node("score_candidate", score_candidate)
    graph.add_node("prioritise_gaps", prioritise_gaps)
    graph.add_node("research_resource", research_resource)
    graph.add_node("assemble_result", assemble_result)

    graph.add_conditional_edges("plan", route_by_plan, {
        "extract_jd_requirements": "extract_requirements",
        "score_candidate_against_requirements": "score_candidate",
        "prioritise_skill_gaps": "prioritise_gaps",
        "research_skill_resources": "research_resource",
        "assemble_result": "assemble_result",
    })
    graph.add_conditional_edges("extract_requirements", route_by_plan, {
        "extract_jd_requirements": "extract_requirements",
        "score_candidate_against_requirements": "score_candidate",
        "prioritise_skill_gaps": "prioritise_gaps",
        "research_skill_resources": "research_resource",
        "assemble_result": "assemble_result",
    })
    graph.add_conditional_edges("score_candidate", route_by_plan, {
        "extract_jd_requirements": "extract_requirements",
        "score_candidate_against_requirements": "score_candidate",
        "prioritise_skill_gaps": "prioritise_gaps",
        "research_skill_resources": "research_resource",
        "assemble_result": "assemble_result",
    })
    graph.add_conditional_edges("prioritise_gaps", route_by_plan, {
        "extract_jd_requirements": "extract_requirements",
        "score_candidate_against_requirements": "score_candidate",
        "prioritise_skill_gaps": "prioritise_gaps",
        "research_skill_resources": "research_resource",
        "assemble_result": "assemble_result",
    })
    graph.add_conditional_edges("research_resource", route_by_plan, {
        "extract_jd_requirements": "extract_requirements",
        "score_candidate_against_requirements": "score_candidate",
        "prioritise_skill_gaps": "prioritise_gaps",
        "research_skill_resources": "research_resource",
        "assemble_result": "assemble_result",
    })
    graph.add_edge("assemble_result", END)

    graph.set_entry_point("plan")
    return graph
