from __future__ import annotations

from typing import Protocol, TypeVar

from pydantic import BaseModel

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


class LLMClient(Protocol):
    def complete_json(self, prompt: str, schema: type[BaseModelT]) -> BaseModelT: ...

    def usage(self) -> dict[str, int] | None: ...

    def call_count(self) -> int: ...
