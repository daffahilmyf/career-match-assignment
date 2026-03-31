from __future__ import annotations

from dataclasses import dataclass
from typing import Type, TypeVar

from pydantic import BaseModel

from pelgo.ports.llm import LLMClient

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


@dataclass(frozen=True)
class NullLLMClient(LLMClient):
    def complete_json(self, prompt: str, schema: Type[BaseModelT]) -> BaseModelT:
        raise RuntimeError("LLM client is not configured")
