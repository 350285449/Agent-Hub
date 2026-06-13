from __future__ import annotations

from collections.abc import Callable
from typing import Generic, TypeVar

from ..config import AgentConfig, normalize_provider


ProviderT = TypeVar("ProviderT")
ProviderFactory = Callable[[AgentConfig], ProviderT]


class ProviderRegistry(Generic[ProviderT]):
    """Small registry for selecting provider adapter factories by normalized key."""

    def __init__(self) -> None:
        self._factories: dict[str, ProviderFactory[ProviderT]] = {}

    def register(self, key: str, factory: ProviderFactory[ProviderT]) -> None:
        self._factories[_normalize_key(key)] = factory

    def create(self, agent: AgentConfig) -> ProviderT:
        key = provider_registry_key(agent)
        factory = self._factories.get(key)
        if factory is None:
            raise KeyError(key)
        return factory(agent)

    def keys(self) -> list[str]:
        return sorted(self._factories)


def provider_registry_key(agent: AgentConfig) -> str:
    provider = normalize_provider(agent.provider)
    provider_type = (agent.provider_type or agent.provider).lower()
    if provider_type == "codex-cli" or provider == "codex-cli":
        return "codex-cli"
    if provider_type in {"ollama", "ollama-local"}:
        return "ollama"
    if provider_type == "groq":
        return "groq"
    if provider_type == "openrouter":
        return "openrouter"
    if provider in {"openai", "openai-compatible"}:
        return "openai-chat"
    if provider == "local-research":
        return "local-research"
    if provider == "anthropic":
        return "anthropic"
    if provider == "gemini":
        return "gemini"
    if provider == "echo":
        return "echo"
    return provider


def _normalize_key(key: str) -> str:
    return str(key or "").strip().lower()


__all__ = ["ProviderFactory", "ProviderRegistry", "provider_registry_key"]
