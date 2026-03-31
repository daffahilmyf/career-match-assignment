from __future__ import annotations

from typing import Literal

from pelgo.application.config import AppSettings
from pelgo.application.langgraph_orchestrator import LangGraphOrchestrator
from pelgo.application.orchestrator import AgentOrchestrator
from pelgo.application.state import AgentState
from pelgo.application.langgraph_graph import build_graph
from pelgo.ports.llm import LLMClient
from pelgo.ports.tooling import ToolRegistry


Provider = Literal["langgraph", "adk"]


def get_orchestrator(
    provider: Provider,
    tools: ToolRegistry,
    settings: AppSettings | None = None,
    llm: LLMClient | None = None,
) -> AgentOrchestrator:
    settings = settings or AppSettings()
    if provider == "langgraph":
        graph = build_graph(tools, settings, llm)
        return LangGraphOrchestrator(graph=graph)
    if provider == "adk":
        raise NotImplementedError("ADK provider is not wired yet")
    raise ValueError(f"Unknown provider: {provider}")


def run_agent(
    provider: Provider,
    tools: ToolRegistry,
    initial_state: AgentState,
    settings: AppSettings | None = None,
    llm: LLMClient | None = None,
) -> AgentState:
    orchestrator = get_orchestrator(provider, tools, settings, llm)
    return orchestrator.run(initial_state)
