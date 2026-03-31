from __future__ import annotations

from typing import Protocol, Type, TypeVar

from pydantic import BaseModel

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


class LLMClient(Protocol):
    def complete_json(self, prompt: str, schema: Type[BaseModelT]) -> BaseModelT: ...
