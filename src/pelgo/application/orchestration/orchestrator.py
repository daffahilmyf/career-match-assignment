from __future__ import annotations

from typing import Protocol

from pelgo.application.orchestration.state import AgentState


class AgentOrchestrator(Protocol):
    def run(self, initial_state: AgentState) -> AgentState: ...
