from __future__ import annotations

from dataclasses import dataclass
from typing import Type, TypeVar

from pydantic import BaseModel

from langchain_openai import ChatOpenAI

from pelgo.ports.llm import LLMClient

BaseModelT = TypeVar("BaseModelT", bound=BaseModel)


@dataclass(frozen=True)
class LangChainOpenAIClient(LLMClient):
    api_key: str
    model: str

    def complete_json(self, prompt: str, schema: Type[BaseModelT]) -> BaseModelT:
        model = ChatOpenAI(model=self.model, api_key=self.api_key)
        structured = model.with_structured_output(schema)
        result = structured.invoke(prompt)
        if isinstance(result, schema):
            return result
        return schema.model_validate(result)
