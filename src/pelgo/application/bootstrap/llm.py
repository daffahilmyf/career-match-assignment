from __future__ import annotations

from pelgo.adapters.llm.langchain_openai_client import LangChainOpenAIClient
from pelgo.adapters.llm.null_client import NullLLMClient
from pelgo.application.config import AppSettings
from pelgo.ports.llm import LLMClient


def build_llm_client(settings: AppSettings | None = None) -> LLMClient:
    settings = settings or AppSettings()
    provider = (getattr(settings, "llm_provider", None) or "").lower()
    if provider in {"langchain_openai", "openai"}:
        api_key = getattr(settings, "llm_api_key", None)
        model = getattr(settings, "llm_model", None)
        if not api_key or not model:
            raise ValueError("LLM_API_KEY and LLM_MODEL are required for OpenAI")
        return LangChainOpenAIClient(
            api_key=api_key,
            model=model,
        )
    return NullLLMClient()


def require_llm_client(settings: AppSettings | None = None) -> LLMClient:
    settings = settings or AppSettings()
    provider = (getattr(settings, "llm_provider", None) or "").lower()
    if provider in {"", "none", "null"}:
        raise RuntimeError("LLM_PROVIDER must be set for LLM-only mode")
    client = build_llm_client(settings)
    if isinstance(client, NullLLMClient):
        raise RuntimeError("LLM client is not configured")
    return client
