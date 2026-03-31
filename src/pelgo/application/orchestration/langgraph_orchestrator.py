from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from pelgo.application.orchestration.orchestrator import AgentOrchestrator
from pelgo.application.orchestration.state import AgentState


@dataclass(frozen=True)
class LangGraphOrchestrator(AgentOrchestrator):
    graph: Any

    def run(self, initial_state: AgentState) -> AgentState:
        runnable = self.graph
        if hasattr(runnable, "compile"):
            runnable = runnable.compile()
        return runnable.invoke(initial_state)

