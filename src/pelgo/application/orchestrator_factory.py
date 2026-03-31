from __future__ import annotations

from typing import Literal

from pelgo.application.langgraph_orchestrator import LangGraphOrchestrator
from pelgo.application.orchestrator import AgentOrchestrator
from pelgo.application.state import AgentState
from pelgo.application.langgraph_graph import build_graph
from pelgo.ports.tooling import ToolRegistry


Provider = Literal["langgraph", "adk"]


def get_orchestrator(provider: Provider, tools: ToolRegistry) -> AgentOrchestrator:
    if provider == "langgraph":
        graph = build_graph(tools)
        return LangGraphOrchestrator(graph=graph)
    if provider == "adk":
        raise NotImplementedError("ADK provider is not wired yet")
    raise ValueError(f"Unknown provider: {provider}")


def run_agent(provider: Provider, tools: ToolRegistry, initial_state: AgentState) -> AgentState:
    orchestrator = get_orchestrator(provider, tools)
    return orchestrator.run(initial_state)
