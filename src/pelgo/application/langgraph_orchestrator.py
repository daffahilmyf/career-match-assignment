from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pelgo.application.orchestrator import AgentOrchestrator
from pelgo.application.state import AgentState


@dataclass(frozen=True)
class LangGraphOrchestrator(AgentOrchestrator):
    graph: Any

    def run(self, initial_state: AgentState) -> AgentState:
        return self.graph.invoke(initial_state)
