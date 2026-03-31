from __future__ import annotations

from dataclasses import dataclass, field
from typing import Type, TypeVar

from pydantic import BaseModel, SecretStr

from langchain_openai import ChatOpenAI

from pelgo.ports.llm import LLMClient

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


@dataclass
class LangChainOpenAIClient(LLMClient):
    api_key: str
    model: str
    _usage: dict[str, int] = field(default_factory=dict)
    _call_count: int = 0

    def complete_json(self, prompt: str, schema: Type[BaseModelT]) -> BaseModelT:
        self._call_count += 1
        model = ChatOpenAI(model=self.model, api_key=SecretStr(self.api_key))
        structured = model.with_structured_output(schema, include_raw=True)
        result = structured.invoke(prompt)
        raw = result.get("raw")
        if raw is not None and hasattr(raw, "response_metadata"):
            token_usage = raw.response_metadata.get("token_usage")
            if isinstance(token_usage, dict):
                for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
                    value = token_usage.get(key)
                    if isinstance(value, int):
                        self._usage[key] = self._usage.get(key, 0) + value
        parsed = result.get("parsed")
        if isinstance(parsed, schema):
            return parsed
        if parsed is not None:
            return schema.model_validate(parsed)
        return schema.model_validate(result)

    def usage(self) -> dict[str, int] | None:
        return dict(self._usage) if self._usage else None

    def call_count(self) -> int:
        return self._call_count
