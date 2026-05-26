from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..config import AgentConfig, HubConfig, is_free_agent, normalize_provider
from ..models import HubRequest, ProviderResult
from ..providers import Provider, ProviderError, create_provider
from ..providers.base import ChatResponse, ProviderAdapter, StreamChunk
from ..streaming import normalize_stream_chunk


ProviderFactory = Callable[[AgentConfig], Provider]
HealthSnapshot = Callable[..., dict[str, dict[str, Any]]]


@dataclass(slots=True)
class ProviderModelInfo:
    agent: str
    provider: str
    provider_type: str
    model: str
    available: bool
    free: bool
    context_window: int | None = None
    supports_streaming: bool = False
    supports_tools: bool = False
    supports_vision: bool = False

    def to_dict(self) -> dict[str, Any]:
        return {
            "agent": self.agent,
            "provider": self.provider,
            "provider_type": self.provider_type,
            "model": self.model,
            "available": self.available,
            "free": self.free,
            "context_window": self.context_window,
            "supports_streaming": self.supports_streaming,
            "supports_tools": self.supports_tools,
            "supports_vision": self.supports_vision,
        }


class ProviderManager:
    """Registry and adapter gateway for configured providers."""

    def __init__(
        self,
        config: HubConfig,
        *,
        provider_factory: ProviderFactory = create_provider,
        health_snapshot: HealthSnapshot | None = None,
    ) -> None:
        self.config = config
        self.provider_factory = provider_factory
        self._health_snapshot = health_snapshot

    def register_provider(self, agent: AgentConfig) -> None:
        self.config.agents[agent.name] = agent

    def unregister_provider(self, agent_name: str) -> None:
        self.config.agents.pop(agent_name, None)

    def get_agent(self, agent_or_name: AgentConfig | str) -> AgentConfig:
        if isinstance(agent_or_name, AgentConfig):
            return agent_or_name
        agent = self.config.agents.get(agent_or_name)
        if agent is None:
            raise ProviderError(
                f"Unknown provider agent {agent_or_name!r}",
                retryable=False,
                error_type="configuration",
            )
        return agent

    def create(self, agent_or_name: AgentConfig | str) -> Provider:
        return self.provider_factory(self.get_agent(agent_or_name))

    def chat(self, agent_or_name: AgentConfig | str, request: HubRequest) -> ProviderResult:
        adapter = self.create(agent_or_name)
        chat = getattr(adapter, "chat", None)
        if callable(chat):
            response = chat(request)
            return self._as_provider_result(adapter, response)
        complete = getattr(adapter, "complete", None)
        if callable(complete):
            return complete(request)
        agent = self.get_agent(agent_or_name)
        raise ProviderError(
            f"Provider adapter {agent.name!r} does not implement chat() or complete()",
            retryable=False,
            error_type="configuration",
        )

    def stream(self, agent_or_name: AgentConfig | str, request: HubRequest) -> Any:
        adapter = self.create(agent_or_name)
        stream = getattr(adapter, "stream", None)
        if not callable(stream):
            agent = self.get_agent(agent_or_name)
            raise ProviderError(
                f"Provider adapter {agent.name!r} does not implement stream()",
                retryable=False,
                error_type="configuration",
            )
        return self._as_stream_chunks(adapter, stream(request))

    def provider_names(self, *, available_only: bool = False) -> list[str]:
        rows = self.models(include_unavailable=not available_only)
        return [row.agent for row in rows if not available_only or row.available]

    def models(self, *, include_unavailable: bool = True) -> list[ProviderModelInfo]:
        health = self.health_snapshot()
        rows: list[ProviderModelInfo] = []
        for agent in self.config.agents.values():
            row_health = health.get(agent.name, {})
            available = self._agent_available(agent, row_health)
            if not available and not include_unavailable:
                continue
            rows.append(
                ProviderModelInfo(
                    agent=agent.name,
                    provider=agent.provider,
                    provider_type=agent.provider_type or normalize_provider(agent.provider),
                    model=agent.model,
                    available=available,
                    free=is_free_agent(agent),
                    context_window=agent.context_window,
                    supports_streaming=bool(agent.supports_streaming),
                    supports_tools=bool(agent.supports_tools or agent.supports_function_calling),
                    supports_vision=bool(agent.supports_vision),
                )
            )
        return rows

    def available_models(self) -> list[dict[str, Any]]:
        return [row.to_dict() for row in self.models(include_unavailable=False)]

    def health_snapshot(self, *, include_history: bool = False) -> dict[str, dict[str, Any]]:
        if self._health_snapshot is None:
            return {}
        try:
            return self._health_snapshot(include_history=include_history)
        except TypeError:
            return self._health_snapshot()

    def _agent_available(self, agent: AgentConfig, health: dict[str, Any]) -> bool:
        if not agent.enabled:
            return False
        if self.config.free_only and not is_free_agent(agent):
            return False
        if health and health.get("available") is False:
            return False
        return True

    def _as_provider_result(self, adapter: Provider, response: Any) -> ProviderResult:
        if isinstance(response, ProviderResult):
            return response
        if isinstance(response, ChatResponse):
            return response.to_provider_result()
        normalize_response = getattr(adapter, "normalize_response", None)
        if callable(normalize_response):
            normalized = normalize_response(response)
            if isinstance(normalized, ChatResponse):
                return normalized.to_provider_result()
        if isinstance(response, dict):
            return ProviderResult(
                text=str(response.get("text", "")),
                model=str(response.get("model") or getattr(adapter, "agent").model),
                raw=dict(response),
                usage=dict(response.get("usage") or {}),
                finish_reason=response.get("finish_reason"),
            )
        raise ProviderError(
            f"Provider adapter returned unsupported response type {type(response).__name__}",
            retryable=False,
            error_type="invalid_provider_response",
        )

    def _as_stream_chunks(self, adapter: Provider, source: Any) -> Any:
        for item in source:
            chunk = normalize_stream_chunk(
                item,
                default_model=getattr(adapter, "agent").model,
            )
            if chunk is not None:
                yield chunk


__all__ = ["ProviderFactory", "ProviderManager", "ProviderModelInfo"]
