from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..config import AgentConfig
from ..provider_presets import PROVIDER_METADATA, ProviderMetadata


@dataclass(frozen=True, slots=True)
class ProviderCapabilities:
    """Static capabilities advertised by a provider integration."""

    context_window: int | None = None
    supports_tools: bool | None = None
    supports_json: bool | None = None
    supports_streaming: bool | None = None
    supports_vision: bool | None = None
    supports_function_calling: bool | None = None

    def to_agent_fields(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "context_window": self.context_window,
                "supports_tools": self.supports_tools,
                "supports_json": self.supports_json,
                "supports_streaming": self.supports_streaming,
                "supports_vision": self.supports_vision,
                "supports_function_calling": self.supports_function_calling,
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderPricing:
    """Known per-million-token pricing for a provider/model family."""

    cost_per_million_input: float | None = None
    cost_per_million_output: float | None = None
    currency: str = "USD"

    def to_agent_fields(self) -> dict[str, Any]:
        return _drop_empty(
            {
                "cost_per_million_input": self.cost_per_million_input,
                "cost_per_million_output": self.cost_per_million_output,
            }
        )


@dataclass(frozen=True, slots=True)
class ProviderDescriptor:
    """Provider SDK metadata that can generate AgentConfig-compatible entries."""

    provider_type: str
    display_name: str
    provider: str = "openai-compatible"
    base_url: str | None = None
    api_key_env: str | None = None
    chat_completions_path: str | None = None
    auth_scheme: str = "bearer"
    headers: dict[str, str] = field(default_factory=dict)
    capabilities: ProviderCapabilities = field(default_factory=ProviderCapabilities)
    pricing: ProviderPricing = field(default_factory=ProviderPricing)
    default_free: bool | None = None
    default_timeout_seconds: float = 120.0
    default_cooldown_seconds: float = 120.0
    notes: str = ""
    models: tuple[str, ...] = ()

    def to_agent_dict(
        self,
        *,
        name: str,
        model: str,
        enabled: bool = False,
        free: bool | None = None,
        **overrides: Any,
    ) -> dict[str, Any]:
        data: dict[str, Any] = {
            "name": name,
            "provider": self.provider,
            "provider_type": self.provider_type,
            "model": model,
            "enabled": enabled,
            "free": self.default_free if free is None else free,
            "api_key_env": self.api_key_env,
            "base_url": self.base_url,
            "chat_completions_path": self.chat_completions_path,
            "timeout_seconds": self.default_timeout_seconds,
            "cooldown_seconds": self.default_cooldown_seconds,
            "headers": dict(self.headers),
            **self.capabilities.to_agent_fields(),
            **self.pricing.to_agent_fields(),
        }
        data.update({key: value for key, value in overrides.items() if value is not None})
        return _drop_empty(data)

    def create_agent(
        self,
        *,
        name: str,
        model: str,
        enabled: bool = False,
        free: bool | None = None,
        **overrides: Any,
    ) -> AgentConfig:
        return AgentConfig(**self.to_agent_dict(
            name=name,
            model=model,
            enabled=enabled,
            free=free,
            **overrides,
        ))


def descriptor_from_metadata(metadata: ProviderMetadata) -> ProviderDescriptor:
    return ProviderDescriptor(
        provider_type=metadata.provider_type,
        display_name=metadata.display_name,
        provider=metadata.provider,
        base_url=metadata.base_url,
        api_key_env=metadata.api_key_env,
        chat_completions_path=metadata.chat_completions_path,
        headers=dict(metadata.default_headers),
        capabilities=ProviderCapabilities(
            supports_tools=metadata.supports_tools,
            supports_json=metadata.supports_json,
            supports_streaming=metadata.supports_streaming,
            supports_vision=False,
            supports_function_calling=metadata.supports_function_calling,
        ),
        default_free=metadata.free,
        notes=metadata.notes,
    )


def builtin_provider_descriptors() -> dict[str, ProviderDescriptor]:
    return {
        provider_type: descriptor_from_metadata(metadata)
        for provider_type, metadata in PROVIDER_METADATA.items()
    }


def _drop_empty(data: dict[str, Any]) -> dict[str, Any]:
    return {
        key: value
        for key, value in data.items()
        if value is not None and value != {} and value != []
    }


__all__ = [
    "ProviderCapabilities",
    "ProviderDescriptor",
    "ProviderPricing",
    "builtin_provider_descriptors",
    "descriptor_from_metadata",
]
