from __future__ import annotations

from uuid import uuid4

from pelgo.application.config import AppSettings
from pelgo.application.llm_factory import require_llm_client
from pelgo.application.orchestrator_factory import run_agent
from pelgo.application.tool_registry import build_tools
from pelgo.application.state import AgentState
from pelgo.domain.model.agent_evaluation_schema import AgentEvaluationResult


def run_once(candidate_profile: str, job_input: str) -> dict[str, object]:
    settings = AppSettings()
    llm = require_llm_client(settings)
    tools = build_tools(llm=llm, settings=settings)
    state: AgentState = {
        "job_id": str(uuid4()),
        "candidate_profile": candidate_profile,
        "job_input": job_input,
    }
    final_state = run_agent("langgraph", tools, state, settings, llm)
    result = final_state.get("result")
    if result is None:
        raise RuntimeError("Agent did not produce a result")
    typed_result = AgentEvaluationResult.model_validate(result)
    return typed_result.model_dump(by_alias=True, mode="json")
