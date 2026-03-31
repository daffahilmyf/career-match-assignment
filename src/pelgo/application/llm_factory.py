from __future__ import annotations

from pelgo.adapters.llm.langchain_openai_client import LangChainOpenAIClient
from pelgo.adapters.llm.null_client import NullLLMClient
from pelgo.application.config import AppSettings
from pelgo.ports.llm import LLMClient


def build_llm_client(settings: AppSettings | None = None) -> LLMClient:
    settings = settings or AppSettings()
    provider = (settings.llm_provider or "").lower()
    if provider in {"langchain_openai", "openai"}:
        if not settings.llm_api_key or not settings.llm_model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required for OpenAI")
        return LangChainOpenAIClient(
            api_key=settings.llm_api_key,
            model=settings.llm_model,
        )
    return NullLLMClient()
