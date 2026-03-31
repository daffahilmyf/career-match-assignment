from __future__ import annotations

from dataclasses import dataclass

import pytest
import requests
from pydantic import BaseModel

from pelgo.adapters.tools import tool_suite
from pelgo.application.config import AppSettings
from pelgo.application.orchestration.langgraph_graph import build_graph
from pelgo.domain.model.shared_types import ConfidenceLevel, ResourceType
from pelgo.domain.model.tool_schema import (
    ExtractJDRequirementsInput,
    ExtractJDRequirementsOutput,
    PrioritiseSkillGapsInput,
    PrioritiseSkillGapsOutput,
    PrioritisedSkillGap,
    ResearchSkillResourcesInput,
    ResearchSkillResourcesOutput,
    ScoreCandidateDimensionScores,
    ScoreCandidateInput,
    ScoreCandidateOutput,
    SkillResource,
)


class FakeLLM:
    def __init__(self, *, should_stop: bool = False) -> None:
        self._call_count = 0
        self.should_stop = should_stop

    def complete_json(self, prompt: str, schema: type[BaseModel]) -> BaseModel:
        self._call_count += 1
        if schema.__name__ == "ReasoningResponse":
            return schema(reasoning="Reasoning summary")
        if schema.__name__ == "PlanResponse":
            return schema(next_step="assemble_result", should_stop=self.should_stop)
        raise AssertionError(f"Unexpected schema {schema.__name__}")

    def usage(self) -> dict[str, int] | None:
        return {"total_tokens": self._call_count}

    def call_count(self) -> int:
        return self._call_count



@dataclass(frozen=True)
class FailingExtractTool:
    name = "extract_jd_requirements"
    input_model = ExtractJDRequirementsInput
    output_model = ExtractJDRequirementsOutput

    def __call__(self, payload: ExtractJDRequirementsInput) -> ExtractJDRequirementsOutput:
        raise requests.Timeout("jd fetch timed out")

@dataclass(frozen=True)
class ExtractTool:
    name = "extract_jd_requirements"
    input_model = ExtractJDRequirementsInput
    output_model = ExtractJDRequirementsOutput

    def __call__(self, payload: ExtractJDRequirementsInput) -> ExtractJDRequirementsOutput:
        return ExtractJDRequirementsOutput(
            required_skills=["python", "aws"],
            nice_to_have_skills=[],
            seniority_level="senior",
            domain="backend",
            responsibilities=["build services"],
        )


@dataclass(frozen=True)
class ScoreTool:
    confidence: ConfidenceLevel
    gap_skills: list[str]
    name = "score_candidate_against_requirements"
    input_model = ScoreCandidateInput
    output_model = ScoreCandidateOutput

    def __call__(self, payload: ScoreCandidateInput) -> ScoreCandidateOutput:
        return ScoreCandidateOutput(
            overall_score=70,
            confidence=self.confidence,
            dimension_scores=ScoreCandidateDimensionScores(skills=70, experience=80, seniority_fit=90),
            matched_skills=["python"],
            gap_skills=self.gap_skills,
        )


@dataclass(frozen=True)
class PrioritiseTool:
    name = "prioritise_skill_gaps"
    input_model = PrioritiseSkillGapsInput
    output_model = PrioritiseSkillGapsOutput

    def __call__(self, payload: PrioritiseSkillGapsInput) -> PrioritiseSkillGapsOutput:
        return PrioritiseSkillGapsOutput(
            ranked_skills=[
                PrioritisedSkillGap(
                    skill=skill,
                    priority_rank=index,
                    estimated_match_gain_pct=max(5, 20 - (index - 1) * 5),
                    rationale=f"priority {index}",
                )
                for index, skill in enumerate(payload.gap_skills, start=1)
            ]
        )


@dataclass(frozen=True)
class EmptyPrioritiseTool:
    name = "prioritise_skill_gaps"
    input_model = PrioritiseSkillGapsInput
    output_model = PrioritiseSkillGapsOutput

    def __call__(self, payload: PrioritiseSkillGapsInput) -> PrioritiseSkillGapsOutput:
        return PrioritiseSkillGapsOutput(ranked_skills=[])



@dataclass(frozen=True)
class FailingResearchTool:
    name = "research_skill_resources"
    input_model = ResearchSkillResourcesInput
    output_model = ResearchSkillResourcesOutput

    def __call__(self, payload: ResearchSkillResourcesInput) -> ResearchSkillResourcesOutput:
        raise requests.Timeout("research timed out")

@dataclass(frozen=True)
class ResearchTool:
    name = "research_skill_resources"
    input_model = ResearchSkillResourcesInput
    output_model = ResearchSkillResourcesOutput

    def __call__(self, payload: ResearchSkillResourcesInput) -> ResearchSkillResourcesOutput:
        return ResearchSkillResourcesOutput(
            resources=[
                SkillResource(
                    title=f"Learn {payload.skill_name}",
                    url=tool_suite._http_url("https://example.com/resource"),
                    estimated_hours=8,
                    type=ResourceType.doc,
                )
            ],
            relevance_score=80,
        )


def _invoke_graph(llm: FakeLLM, score_tool: ScoreTool):
    tools = {
        "extract_jd_requirements": ExtractTool(),
        "score_candidate_against_requirements": score_tool,
        "prioritise_skill_gaps": PrioritiseTool(),
        "research_skill_resources": ResearchTool(),
    }
    settings = AppSettings(top_gap_limit=max(1, len(score_tool.gap_skills)))
    graph = build_graph(tools, settings, llm).compile()
    return graph.invoke(
        {
            "job_id": "job-1",
            "candidate_profile": '{"skills": ["python"], "years_experience": 6}',
            "job_input": "Senior backend engineer with Python and AWS",
        }
    )


def test_high_confidence_run_has_no_duplicate_tool_traces() -> None:
    state = _invoke_graph(
        FakeLLM(),
        ScoreTool(confidence=ConfidenceLevel.high, gap_skills=["aws"]),
    )

    tool_names = [call.tool for call in state["result"].agent_trace.tool_calls]

    assert tool_names == [
        "extract_jd_requirements",
        "score_candidate_against_requirements",
        "prioritise_skill_gaps",
        "research_skill_resources",
    ]
    assert len(tool_names) == len(set(tool_names))


def test_low_confidence_run_forces_research_before_assemble() -> None:
    state = _invoke_graph(
        FakeLLM(should_stop=True),
        ScoreTool(confidence=ConfidenceLevel.low, gap_skills=["aws", "ci cd"]),
    )

    result = state["result"]
    tool_names = [call.tool for call in result.agent_trace.tool_calls]

    assert "research_skill_resources" in tool_names
    assert result.learning_plan
    assert result.learning_plan[0].resources
    assert result.agent_trace.fallbacks_triggered == 0


def test_empty_prioritized_gaps_does_not_loop_and_assembles_result():
    tools = {
        "extract_jd_requirements": ExtractTool(),
        "score_candidate_against_requirements": ScoreTool(ConfidenceLevel.low, ["ci cd"]),
        "prioritise_skill_gaps": EmptyPrioritiseTool(),
        "research_skill_resources": ResearchTool(),
    }
    settings = AppSettings()
    graph = build_graph(tools, settings, llm=None).compile()

    state = graph.invoke(
        {
            "job_id": "job-3",
            "job_input": "Senior backend engineer with CI/CD ownership",
            "candidate_profile": '{"skills": ["python", "postgresql"], "experience": ["6 years backend"]}',
            "trace_tool_calls": [],
            "resources": [],
            "researched_resources": [],
            "fallbacks_triggered": 0,
            "total_llm_calls": 0,
        }
    )

    result = state["result"]
    assert result.gap_skills == ["ci cd"]
    assert result.learning_plan == []
    tool_names = [call.tool for call in result.agent_trace.tool_calls]
    assert tool_names == [
        "extract_jd_requirements",
        "score_candidate_against_requirements",
        "prioritise_skill_gaps",
    ]


def test_research_failures_do_not_loop_forever():
    tools = {
        "extract_jd_requirements": ExtractTool(),
        "score_candidate_against_requirements": ScoreTool(ConfidenceLevel.low, ["ci cd"]),
        "prioritise_skill_gaps": PrioritiseTool(),
        "research_skill_resources": FailingResearchTool(),
    }
    settings = AppSettings(top_gap_limit=3)
    graph = build_graph(tools, settings, llm=None).compile()

    state = graph.invoke(
        {
            "job_id": "job-4",
            "job_input": "Senior backend engineer with CI/CD ownership",
            "candidate_profile": '{"skills": ["python", "postgresql"], "experience": ["6 years backend"]}',
            "trace_tool_calls": [],
            "resources": [],
            "researched_resources": [],
            "fallbacks_triggered": 0,
            "total_llm_calls": 0,
        }
    )

    result = state["result"]
    assert result.gap_skills == ["ci cd"]
    assert result.learning_plan[0].resources
    assert str(result.learning_plan[0].resources[0].url).startswith("https://ocw.mit.edu/search/?q=")
    tool_names = [call.tool for call in result.agent_trace.tool_calls]
    assert tool_names == [
        "extract_jd_requirements",
        "score_candidate_against_requirements",
        "prioritise_skill_gaps",
        "research_skill_resources",
    ]


def test_unresearched_prioritized_gaps_get_fallback_resources():
    tools = {
        "extract_jd_requirements": ExtractTool(),
        "score_candidate_against_requirements": ScoreTool(ConfidenceLevel.high, ["graphql", "rest api", "sql"]),
        "prioritise_skill_gaps": PrioritiseTool(),
        "research_skill_resources": ResearchTool(),
    }
    settings = AppSettings(top_gap_limit=1)
    graph = build_graph(tools, settings, llm=None).compile()

    state = graph.invoke(
        {
            "job_id": "job-5",
            "candidate_profile": '{"skills": ["python"], "years_experience": 6}',
            "job_input": "Backend role with GraphQL, REST API, and SQL",
        }
    )

    learning_plan = state["result"].learning_plan
    assert len(learning_plan) == 3
    assert all(item.resources for item in learning_plan)
    assert str(learning_plan[1].resources[0].url).startswith("https://ocw.mit.edu/search/?q=")
    assert str(learning_plan[2].resources[0].url).startswith("https://ocw.mit.edu/search/?q=")


def test_jd_url_extraction_failure_raises_instead_of_completing():
    tools = {
        "extract_jd_requirements": FailingExtractTool(),
        "score_candidate_against_requirements": ScoreTool(ConfidenceLevel.high, []),
        "prioritise_skill_gaps": PrioritiseTool(),
        "research_skill_resources": ResearchTool(),
    }
    settings = AppSettings()
    graph = build_graph(tools, settings, llm=None).compile()

    with pytest.raises(RuntimeError, match="JD URL extraction failed"):
        graph.invoke(
            {
                "job_id": "job-url-fail",
                "candidate_profile": '{"skills": ["python"], "years_experience": 6}',
                "job_input": "https://example.com/jobs/backend",
            }
        )
