from __future__ import annotations

from functools import lru_cache

from app.core.config import get_settings
from app.llm.base import LLMProvider
from app.llm.deterministic import DeterministicProvider


@lru_cache
def get_llm() -> LLMProvider:
    """Resolve the configured provider.

    ``auto`` prefers Claude when a key is present and silently falls back to
    the offline rule-based provider otherwise, so a fresh clone runs with no
    configuration.
    """
    settings = get_settings()
    choice = settings.llm_provider
    if choice == "deterministic":
        return DeterministicProvider()
    if choice in ("auto", "anthropic") and settings.anthropic_api_key:
        from app.llm.anthropic_provider import AnthropicProvider

        return AnthropicProvider(settings.anthropic_api_key, settings.anthropic_model)
    if choice == "anthropic":
        raise RuntimeError("LLM_PROVIDER=anthropic but ANTHROPIC_API_KEY is unset")
    return DeterministicProvider()


def reset_llm_cache() -> None:
    get_llm.cache_clear()
